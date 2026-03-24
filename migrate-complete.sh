#!/bin/bash
#
# AAP Complete Migration Script
# Migrates ALL resources from AAP 2.3/2.4 to AAP 2.6
#
# This script uses the proven step-by-step approach that works reliably.
#

set -e  # Exit on error

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  AAP 2.3/2.4 → 2.6 Complete Migration Script               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Activate virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ Error: Virtual environment not found. Run 'python -m venv .venv' first."
    exit 1
fi

# Clean start
echo "🧹 Cleaning previous migration data..."
rm -rf exports xformed migration_state.db
echo "✅ Cleaned"
echo ""

# Step 1: Export
echo "📤 STEP 1: Exporting data from source AAP..."
aap-bridge export --force --yes
if [ $? -ne 0 ]; then
    echo "❌ Export failed!"
    exit 1
fi
echo "✅ Export complete"
echo ""

# Step 2: Transform
echo "🔄 STEP 2: Transforming data for AAP 2.6..."
aap-bridge transform --force
if [ $? -ne 0 ]; then
    echo "❌ Transform failed!"
    exit 1
fi
echo "✅ Transform complete"
echo ""

# Step 3: Import Phase 1 (Infrastructure & Projects)
echo "📥 STEP 3: Importing Phase 1 (Infrastructure & Projects)..."
aap-bridge import --yes --phase phase1
if [ $? -ne 0 ]; then
    echo "❌ Phase 1 import failed!"
    exit 1
fi
echo "✅ Phase 1 import complete"
echo ""

# Step 4: Patch Projects
echo "🔧 STEP 4: Patching projects with SCM details..."
aap-bridge patch-projects
if [ $? -ne 0 ]; then
    echo "⚠️  Project patching failed (may be expected if no projects need patching)"
fi
echo "✅ Project patching complete"
echo ""

# Step 5: Import Phase 3 (Automation - Job Templates, Schedules, Applications, Settings)
echo "📥 STEP 5: Importing Phase 3 (Automation Definitions, Applications, Settings)..."
aap-bridge import --yes \
    --resource-type job_templates \
    --resource-type workflow_job_templates \
    --resource-type schedules \
    --resource-type notification_templates \
    --resource-type applications \
    --resource-type settings

if [ $? -ne 0 ]; then
    echo "⚠️  Phase 3 import had some failures (check log for details)"
else
    echo "✅ Phase 3 import complete"
fi
echo ""

# Show summary
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Migration Summary                                          ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

if [ -f "migration_state.db" ]; then
    echo "📊 Database statistics:"
    sqlite3 migration_state.db <<EOF
SELECT
    resource_type,
    COUNT(*) as total,
    SUM(CASE WHEN target_id IS NOT NULL THEN 1 ELSE 0 END) as imported,
    SUM(CASE WHEN target_id IS NULL THEN 1 ELSE 0 END) as failed
FROM id_mappings
GROUP BY resource_type
ORDER BY resource_type;
EOF
else
    echo "⚠️  No database file found"
fi

echo ""

# Generate project failure analysis if any projects failed
echo "📋 Analyzing project failures..."
aap-bridge analyze-project-failures --output PROJECT-FAILURES-REPORT.md
if [ -f "PROJECT-FAILURES-REPORT.md" ]; then
    # Check if any projects failed
    failed_count=$(sqlite3 migration_state.db "SELECT COUNT(*) FROM id_mappings WHERE resource_type='projects' AND target_id IS NULL;" 2>/dev/null || echo "0")
    if [ "$failed_count" -gt "0" ]; then
        echo "⚠️  $failed_count project(s) failed to import!"
        echo "📄 See PROJECT-FAILURES-REPORT.md for manual fix instructions"
    fi
fi

echo ""
echo "✅ Migration complete!"
echo ""
echo "📁 Exported data: exports/"
echo "📁 Transformed data: xformed/"
echo "📁 Migration database: migration_state.db"
echo "📁 Failure analysis: PROJECT-FAILURES-REPORT.md"
echo ""
