import { Icon } from './Icon';

/** A clip still (160x90), or a neutral placeholder with a small camera glyph when there is none. */
export function ClipThumb({ url }: { url: string | null }) {
  return (
    <div className="thumb">
      {url ? <img src={url} alt="" width={160} height={90} loading="lazy" /> : <Icon name="camera" size={20} />}
    </div>
  );
}
