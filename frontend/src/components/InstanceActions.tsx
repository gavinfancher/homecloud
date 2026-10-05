import { useState } from 'react'
import type { VM } from '../api'
import { IconPause, IconPlay, IconStop, IconTrash } from './Icons'
import { useToast } from './Toast'
import { useStore } from '../lib/store'

export function InstanceActions({ vm }: { vm: VM }) {
  const { api, refresh, openJob } = useStore()
  const toast = useToast()
  const [busy, setBusy] = useState(false)

  async function act(fn: () => Promise<unknown>, msg?: string) {
    setBusy(true)
    try {
      await fn()
      if (msg) toast.success(msg)
      await refresh()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="instance-actions">
      {vm.status === 'running' ? (
        <>
          <button
            className="btn-icon"
            title="Pause"
            disabled={busy}
            onClick={() => act(() => api.suspend(vm.vmid), `Paused ${vm.name}`)}
          >
            <IconPause />
          </button>
          <button
            className="btn-icon"
            title="Stop"
            disabled={busy}
            onClick={() => act(() => api.stop(vm.vmid), `Stopped ${vm.name}`)}
          >
            <IconStop />
          </button>
        </>
      ) : vm.status === 'paused' ? (
        <button
          className="btn-icon ok"
          title="Resume"
          disabled={busy}
          onClick={() => act(() => api.resume(vm.vmid), `Resumed ${vm.name}`)}
        >
          <IconPlay />
        </button>
      ) : (
        <button
          className="btn-icon ok"
          title="Start"
          disabled={busy}
          onClick={() => act(() => api.start(vm.vmid), `Started ${vm.name}`)}
        >
          <IconPlay />
        </button>
      )}
      <button
        className="btn-icon danger"
        title="Delete"
        disabled={busy}
        onClick={() => {
          if (confirm(`Delete ${vm.name}? This permanently destroys the VM.`)) {
            act(async () => {
              const { job_id } = await api.remove(vm.vmid)
              openJob(job_id)
            })
          }
        }}
      >
        <IconTrash />
      </button>
    </div>
  )
}
