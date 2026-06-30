import Anser from 'anser';
import './Ansi.css';

const ansiOptions = { json: true, remove_empty: true, use_classes: true } as const;

export function Ansi({ input }: { input: string }) {
  const data = Anser.ansiToJson(input, ansiOptions);
  return (
    <>
      {data.map((entry, index) => {
        const classes: string[] = [];
        if (entry.fg) classes.push(`${entry.fg}-fg`);
        if (entry.decoration === 'bold') classes.push('ansi-bold');
        if (entry.decoration === 'italic') classes.push('ansi-italic');
        if (entry.decoration === 'underline') classes.push('ansi-underline');
        return (
          <span key={index} className={classes.join(' ') || undefined}>
            {entry.content}
          </span>
        );
      })}
    </>
  );
}
