import { useEffect, useId, useRef, useState } from 'react';
import { type Theme, useTheme } from '../theme';
import Icon from './Icon';

const appearances: { id: Theme; name: string; description: string }[] = [
  { id: 'general', name: 'General', description: 'Original navy workspace' },
  { id: 'light', name: 'Light', description: 'Clear surfaces for daylight' },
  { id: 'black', name: 'Black', description: 'Neutral, deep dark surfaces' },
];

export default function ProfileMenu() {
  const { theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuId = useId();
  const titleId = useId();

  useEffect(() => {
    if (!open) return;
    wrapperRef.current?.querySelector<HTMLInputElement>('input:checked')?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (event.target instanceof Node && !wrapperRef.current?.contains(event.target)) setOpen(false);
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [open]);

  return <div className="profile-menu" ref={wrapperRef} onBlur={event => {
    if (event.relatedTarget instanceof Node && !event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }}>
    <button ref={triggerRef} className="profile-trigger" type="button" aria-label="Profile and appearance" aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? menuId : undefined} onClick={() => setOpen(value => !value)}>
      <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="8" r="3.5" /><path d="M4.5 21v-2a7.5 7.5 0 0 1 15 0v2" /></svg>
      <span>Profile</span><Icon name="chevron" size={12} />
    </button>
    {open && <div id={menuId} className="profile-popover" role="dialog" aria-labelledby={titleId}>
      <div className="profile-heading"><h2 id={titleId}>Profile preferences</h2><button type="button" className="icon-button" aria-label="Close profile preferences" onClick={() => { setOpen(false); triggerRef.current?.focus(); }}><Icon name="close" size={13} /></button></div>
      <fieldset className="appearance-options"><legend>Appearance</legend>
        {appearances.map(appearance => <label key={appearance.id} className={`appearance-option${theme === appearance.id ? ' selected' : ''}`}>
          <input type="radio" name={`${menuId}-appearance`} value={appearance.id} checked={theme === appearance.id} onChange={() => setTheme(appearance.id)} />
          <span className={`theme-preview theme-preview-${appearance.id}`} aria-hidden="true"><i /><b /><em /></span>
          <span className="appearance-copy"><strong>{appearance.name}</strong><small>{appearance.description}</small></span>
          {theme === appearance.id && <Icon name="check" size={14} />}
        </label>)}
      </fieldset>
      <p className="profile-footnote">Appearance is remembered in this browser.</p>
    </div>}
  </div>;
}
