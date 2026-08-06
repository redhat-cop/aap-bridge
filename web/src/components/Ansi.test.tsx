import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Ansi } from './Ansi';

describe('Ansi', () => {
  it('renders plain text', () => {
    render(<Ansi input="hello world" />);
    expect(screen.getByText('hello world')).toBeInTheDocument();
  });

  it('applies ansi-bold for bold sequences', () => {
    const { container } = render(<Ansi input={'\u001b[1mbold\u001b[0m'} />);
    const bold = container.querySelector('.ansi-bold');
    expect(bold).not.toBeNull();
    expect(bold?.textContent).toBe('bold');
  });
});
