import { useEffect, useId, useRef } from "react"

interface ResetDialogProps {
  title: string
  description: string
  cancelLabel: string
  confirmLabel: string
  onCancel: () => void
  onConfirm: () => void
}

export function ResetDialog({ title, description, cancelLabel, confirmLabel, onCancel, onConfirm }: ResetDialogProps) {
  const dialog = useRef<HTMLDialogElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  const descriptionId = useId()
  useEffect(() => {
    const element = dialog.current!
    const previousFocus = document.activeElement as HTMLElement | null
    element.showModal()
    cancel.current?.focus()
    return () => { element.close(); previousFocus?.focus({ preventScroll: true }) }
  }, [])
  return (
    <dialog ref={dialog} className="settings-reset-dialog" aria-labelledby={titleId} aria-describedby={descriptionId} onCancel={(event) => { event.preventDefault(); onCancel() }}>
      <h2 id={titleId}>{title}</h2><p id={descriptionId}>{description}</p>
      <div className="settings-reset-actions">
        <button ref={cancel} className="settings-button" type="button" onClick={onCancel}>{cancelLabel}</button>
        <button className="settings-button" type="button" onClick={onConfirm}>{confirmLabel}</button>
      </div>
    </dialog>
  )
}
