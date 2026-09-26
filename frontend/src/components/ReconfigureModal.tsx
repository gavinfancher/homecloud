import { useState, type FormEvent } from 'react'
import type { RoleSelection, VM } from '../api'
import { IconClose } from './Icons'
import { RoleEditor, defaultSelection, normalizeSelection, selectionValid } from './RoleEditor'
import { useStore } from '../lib/store'
import { useToast } from './Toast'

/** Edit an instance's roles and re-run Ansible against it. */
export function ReconfigureModal({ vm, onClose }: { vm: VM; onClose: () => void }) {
  const { api, roles, refresh, openJob } = useStore()
  const toast = useToast()
  const [edited, setSelection] = useState<RoleSelection[] | null>(null)
  const [busy, setBusy] = useState(false)

  // Instances from before roles existed have none stored; start from defaults.
  const selection =
    edited ?? (vm.roles?.length ? normalizeSelection(roles, vm.roles) : defaultSelection(roles))
  const canSubmit = !busy && selectionValid(selection)

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    try {
      const { job_id } = await api.provision(vm.name, selection)
      toast.success(`Reconfiguring ${vm.name}…`)
      openJob(job_id)
      refresh()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div className="modal-scrim" onClick={onClose} />
      <div className="modal modal-wide" role="dialog" aria-label={`Reconfigure ${vm.name}`}>
        <header className="modal-head">
          <h2>Reconfigure {vm.name}</h2>
          <button className="btn-icon" onClick={onClose} title="Close">
            <IconClose />
          </button>
        </header>

        <form className="modal-form" onSubmit={submit}>
          <div className="modal-body">
            <small className="hint">
              Re-runs Ansible with these roles. Turning a role off stops managing it; it does not
              uninstall anything.
            </small>
            <RoleEditor catalog={roles} value={selection} onChange={setSelection} />
          </div>

          <footer className="modal-foot">
            <button type="button" className="btn btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!canSubmit}>
              {busy ? 'Starting…' : 'Apply'}
            </button>
          </footer>
        </form>
      </div>
    </>
  )
}
