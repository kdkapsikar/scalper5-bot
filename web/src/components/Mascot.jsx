import { BEAR, BULL } from '../lib/mascots.js';

/** The Bull or the Bear (inline SVG, animated by CSS). The SVG strings are constants from this repo. */
export default function Mascot({ who, size = 80, className = '', style }) {
  return (
    <span className={`mascot inline-block ${className}`} style={{ width: size, height: size, ...style }}
      // eslint-disable-next-line react/no-danger
      dangerouslySetInnerHTML={{ __html: who === 'bear' ? BEAR : BULL }} />
  );
}
