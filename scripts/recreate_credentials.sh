#!/bin/bash

#
# AAP Credential Recreation Helper Script
#
# This script helps you recreate credentials in target AAP 2.6
# and track the credential ID mappings for project/template migration.
#

set -e

# Configuration
SOURCE_URL="${SOURCE_URL:-https://localhost:8443/api/v2}"
SOURCE_TOKEN="${SOURCE_TOKEN:-ENOBFlD2GAB2LmCD5P2RqsTEOjbrlA}"
TARGET_URL="${TARGET_URL:-https://localhost:10443/api/controller/v2}"
TARGET_TOKEN="${TARGET_TOKEN:-ea023U8zsSXEBuXXZRpiLidAYMT1aT}"
STATE_DB="${STATE_DB:-migration_state.db}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Functions
print_header() {
    echo -e "${BLUE}===================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}===================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

# Step 1: Export source credentials
export_source_credentials() {
    print_header "Step 1: Exporting Source Credentials"

    print_info "Fetching credentials from source AAP..."
    curl -sk -H "Authorization: Bearer $SOURCE_TOKEN" \
        "$SOURCE_URL/credentials/" \
        -o source_credentials_full.json

    local count=$(jq '.count' source_credentials_full.json)
    print_success "Found $count credentials in source AAP"

    # Create readable summary
    jq -r '.results[] | {
        id: .id,
        name: .name,
        type: .credential_type,
        kind: .kind,
        organization: .organization,
        has_secrets: (.inputs | to_entries | map(select(.value == "$encrypted$")) | length > 0)
    }' source_credentials_full.json > source_credentials_summary.json

    print_success "Credential summary saved to: source_credentials_summary.json"
    echo ""

    # Display summary table
    print_info "Source Credentials:"
    echo "----------------------------------------"
    jq -r '.[] | "\(.id)\t\(.name)\t\(.kind)\t\(if .has_secrets then "🔒 Has Secrets" else "✓ No Secrets" end)"' \
        source_credentials_summary.json | column -t -s $'\t'
    echo ""
}

# Step 2: Show what secrets are needed
show_secrets_needed() {
    print_header "Step 2: Secrets Needed"

    print_warning "The following credentials have encrypted secrets that need to be provided:"
    echo ""

    jq -r '.results[] | select(.inputs | to_entries | map(select(.value == "$encrypted$")) | length > 0) |
        "ID: \(.id) - \(.name) (\(.credential_type))
        Encrypted fields: \(.inputs | to_entries | map(select(.value == "$encrypted$")) | map(.key) | join(", "))
        "' source_credentials_full.json

    echo ""
    print_info "You will need to provide these secrets when recreating credentials."
    print_info "Refer to FIX-CREDENTIALS-GUIDE.md Step 2 for where to find them."
    echo ""
}

# Step 3: Create credential in target (interactive)
create_credential_interactive() {
    local source_id=$1

    print_header "Creating Credential: Source ID $source_id"

    # Get source credential details
    local cred_json=$(jq ".results[] | select(.id == $source_id)" source_credentials_full.json)
    local name=$(echo "$cred_json" | jq -r '.name')
    local type=$(echo "$cred_json" | jq -r '.credential_type')
    local kind=$(echo "$cred_json" | jq -r '.kind')
    local org=$(echo "$cred_json" | jq -r '.organization // "null"')

    print_info "Name: $name"
    print_info "Type: $kind (ID: $type)"
    print_info "Organization: $org"
    echo ""

    # Show current inputs (with encrypted values)
    print_info "Current inputs from source:"
    echo "$cred_json" | jq '.inputs'
    echo ""

    # Ask if user wants to create this credential
    read -p "Do you want to create this credential in target AAP? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_warning "Skipped credential: $name"
        return 1
    fi

    # Get new inputs
    print_info "Enter the credential inputs (in JSON format):"
    print_info "Example: {\"username\": \"admin\", \"password\": \"secretpass\"}"
    read -r new_inputs

    # Validate JSON
    if ! echo "$new_inputs" | jq . > /dev/null 2>&1; then
        print_error "Invalid JSON format"
        return 1
    fi

    # Create credential in target
    print_info "Creating credential in target AAP..."

    local response=$(curl -sk -X POST \
        -H "Authorization: Bearer $TARGET_TOKEN" \
        -H "Content-Type: application/json" \
        "$TARGET_URL/credentials/" \
        -d "{
            \"name\": \"$name\",
            \"credential_type\": $type,
            \"organization\": $org,
            \"inputs\": $new_inputs
        }")

    # Check if successful
    local target_id=$(echo "$response" | jq -r '.id // empty')

    if [ -z "$target_id" ]; then
        print_error "Failed to create credential"
        echo "$response" | jq .
        return 1
    fi

    print_success "Credential created with ID: $target_id"

    # Save mapping
    echo "$source_id,$target_id,$name" >> credential_mappings.csv

    # Update state DB if exists
    if [ -f "$STATE_DB" ]; then
        sqlite3 "$STATE_DB" "INSERT OR REPLACE INTO id_mappings (resource_type, source_id, target_id, resource_name) VALUES ('credentials', $source_id, $target_id, '$name');"
        print_success "Updated state database: $STATE_DB"
    fi

    echo ""
}

# Step 4: Batch create simple credentials (no secrets)
create_no_secret_credentials() {
    print_header "Step 4: Auto-creating Credentials Without Secrets"

    # Find credentials with no encrypted values
    local no_secret_creds=$(jq -r '.results[] | select(.inputs | to_entries | map(select(.value == "$encrypted$")) | length == 0) | .id' source_credentials_full.json)

    if [ -z "$no_secret_creds" ]; then
        print_warning "No credentials found without secrets"
        return
    fi

    for source_id in $no_secret_creds; do
        local cred_json=$(jq ".results[] | select(.id == $source_id)" source_credentials_full.json)
        local name=$(echo "$cred_json" | jq -r '.name')
        local type=$(echo "$cred_json" | jq -r '.credential_type')
        local org=$(echo "$cred_json" | jq -r '.organization // "null"')
        local inputs=$(echo "$cred_json" | jq -c '.inputs')

        print_info "Creating: $name (ID: $source_id)"

        local response=$(curl -sk -X POST \
            -H "Authorization: Bearer $TARGET_TOKEN" \
            -H "Content-Type: application/json" \
            "$TARGET_URL/credentials/" \
            -d "{
                \"name\": \"$name\",
                \"credential_type\": $type,
                \"organization\": $org,
                \"inputs\": $inputs
            }")

        local target_id=$(echo "$response" | jq -r '.id // empty')

        if [ -z "$target_id" ]; then
            print_error "Failed to create: $name"
            echo "$response" | jq .
        else
            print_success "Created: $name (Source: $source_id → Target: $target_id)"
            echo "$source_id,$target_id,$name" >> credential_mappings.csv

            if [ -f "$STATE_DB" ]; then
                sqlite3 "$STATE_DB" "INSERT OR REPLACE INTO id_mappings (resource_type, source_id, target_id, resource_name) VALUES ('credentials', $source_id, $target_id, '$name');"
            fi
        fi
    done

    echo ""
}

# Step 5: Show credential mappings
show_mappings() {
    print_header "Credential ID Mappings"

    if [ ! -f credential_mappings.csv ]; then
        print_warning "No credential mappings found yet"
        return
    fi

    print_info "Source ID → Target ID mappings:"
    echo "----------------------------------------"
    echo "Source,Target,Name"
    cat credential_mappings.csv | column -t -s ','
    echo ""

    if [ -f "$STATE_DB" ]; then
        print_success "Mappings also saved to state database: $STATE_DB"
    fi
}

# Step 6: Update organization galaxy credentials
associate_galaxy_credentials() {
    print_header "Associating Galaxy Credentials to Organizations"

    # Get organizations from source with galaxy credentials
    print_info "Checking source organizations for galaxy credentials..."

    local orgs=$(curl -sk -H "Authorization: Bearer $SOURCE_TOKEN" \
        "$SOURCE_URL/organizations/" | jq -r '.results[] | .id')

    for org_id in $orgs; do
        local org_name=$(curl -sk -H "Authorization: Bearer $SOURCE_TOKEN" \
            "$SOURCE_URL/organizations/$org_id/" | jq -r '.name')

        local galaxy_creds=$(curl -sk -H "Authorization: Bearer $SOURCE_TOKEN" \
            "$SOURCE_URL/organizations/$org_id/galaxy_credentials/" | jq -r '.results[] | .id')

        if [ -z "$galaxy_creds" ]; then
            continue
        fi

        print_info "Organization: $org_name (ID: $org_id)"

        for source_cred_id in $galaxy_creds; do
            local cred_name=$(curl -sk -H "Authorization: Bearer $SOURCE_TOKEN" \
                "$SOURCE_URL/credentials/$source_cred_id/" | jq -r '.name')

            # Get target credential ID from mapping
            local target_cred_id=$(grep "^$source_cred_id," credential_mappings.csv 2>/dev/null | cut -d',' -f2)

            if [ -z "$target_cred_id" ]; then
                print_warning "  Credential not found in mappings: $cred_name (Source ID: $source_cred_id)"
                print_warning "  Please create this credential first"
                continue
            fi

            # Associate in target
            print_info "  Associating: $cred_name (Target ID: $target_cred_id)"

            local response=$(curl -sk -X POST \
                -H "Authorization: Bearer $TARGET_TOKEN" \
                -H "Content-Type: application/json" \
                "$TARGET_URL/organizations/$org_id/galaxy_credentials/" \
                -d "{\"id\": $target_cred_id}")

            if echo "$response" | jq -e '.id' > /dev/null 2>&1; then
                print_success "  Associated: $cred_name to $org_name"
            else
                print_error "  Failed to associate: $cred_name"
                echo "$response" | jq .
            fi
        done

        echo ""
    done
}

# Main menu
main_menu() {
    while true; do
        print_header "AAP Credential Recreation Helper"
        echo "1. Export source credentials"
        echo "2. Show secrets needed"
        echo "3. Auto-create credentials (no secrets)"
        echo "4. Create credential (interactive)"
        echo "5. Show credential mappings"
        echo "6. Associate galaxy credentials to organizations"
        echo "7. Export all for manual review"
        echo "8. Quit"
        echo ""
        read -p "Select option: " -n 1 -r
        echo
        echo ""

        case $REPLY in
            1) export_source_credentials ;;
            2) show_secrets_needed ;;
            3) create_no_secret_credentials ;;
            4)
                read -p "Enter source credential ID: " source_id
                create_credential_interactive "$source_id"
                ;;
            5) show_mappings ;;
            6) associate_galaxy_credentials ;;
            7)
                export_source_credentials
                show_secrets_needed
                print_success "Exported to source_credentials_full.json and source_credentials_summary.json"
                ;;
            8)
                print_success "Done!"
                exit 0
                ;;
            *)
                print_error "Invalid option"
                ;;
        esac

        echo ""
        read -p "Press Enter to continue..."
        clear
    done
}

# Initialize
mkdir -p logs
echo "source_id,target_id,name" > credential_mappings.csv

# Run
main_menu
