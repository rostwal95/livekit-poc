/** Optional operations page. Read-only; no storage, RTC, command or event publisher. */
import './p2-operations.css';
import { OperationsController, OperationsUiError } from './p2-operations-policy';
import { OperationsPanel } from './p2-operations-panel';
let panel: OperationsPanel;
const controller = new OperationsController((state) => panel.render(state));
function observe(work: Promise<void>): void {
  void work.catch((error: unknown) => {
    const code = error instanceof OperationsUiError ? error.code : 'unavailable';
    panel.notice.textContent =
      code === 'cleanup_incomplete'
        ? 'Cleanup is incomplete. Private facts are cleared; the request owner remains retained. Retry Forget after it settles.'
        : code === 'overloaded'
          ? 'The existing read owner is still active. Wait for cleanup before reconnecting.'
          : code === 'invalid_query'
            ? 'Enter the operator credential provided by the local application.'
            : 'The read could not be completed. Retry or Forget this view.';
    panel.notice.hidden = false;
  });
}
panel = new OperationsPanel({
  connect: (token) => observe(controller.connect(token)),
  refresh: () => observe(controller.refresh()),
  retry: () => observe(controller.retry()),
  forget: () => observe(controller.forget()),
  pause: () => {
    if (controller.snapshot().polling) controller.pause();
    else {
      try {
        controller.resume();
      } catch {
        panel.notice.textContent = 'Refresh or Forget this view before resuming updates.';
        panel.notice.hidden = false;
      }
    }
  },
  older: (section) => observe(controller.older(section)),
});
panel.render(controller.snapshot());
document.addEventListener('visibilitychange', () => {
  if (document.hidden) controller.hidden();
});
window.addEventListener(
  'pagehide',
  () => {
    panel.token.value = '';
    observe(controller.forget());
  },
  { once: true },
);
