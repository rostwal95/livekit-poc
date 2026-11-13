/** Optional standalone P3 native text page. No P2 intake, audio or action commands. */
import './p3-background.css';
import { BackgroundController, BackgroundError } from './p3-background-policy';
import { BackgroundPanel } from './p3-background-panel';
import { NativeBackgroundPort } from './p3-background-room';
import { projectNativeObservation } from './p3-background-wire';
import type { NativeObservation } from './p3-background-wire';
let panel: BackgroundPanel<NativeObservation>;
const controller = new BackgroundController<NativeObservation>(
  (token, callbacks) => new NativeBackgroundPort(token, callbacks),
  (state) => panel.render(state),
  (value) =>
    value.state === 'unknown' ? (value.error === 'capacity' ? 'overloaded' : 'unavailable') : null,
);
function observe(invoke: () => Promise<void>): void {
  const before = controller.snapshot();
  void invoke().catch((error: unknown) => {
    // A late rejected waiter cannot overwrite the view produced by End/Forget/new ownership.
    if (controller.snapshot() !== before) {
      panel.render(controller.snapshot());
      return;
    }
    const code: unknown =
      error instanceof BackgroundError
        ? Object.getOwnPropertyDescriptor(error, 'code')?.value
        : null;
    panel.showError(
      code === 'invalid' ||
        code === 'access_denied' ||
        code === 'unknown' ||
        code === 'overloaded' ||
        code === 'closed' ||
        code === 'cleanup_incomplete'
        ? code
        : 'unavailable',
    );
  });
}
panel = new BackgroundPanel(
  {
    connect: (token) => observe(() => controller.connect(token)),
    send: (text) => observe(() => controller.send(text)),
    refresh: () => observe(() => controller.refresh()),
    end: () => observe(() => controller.end()),
    forget: () => observe(() => controller.forget()),
  },
  projectNativeObservation,
);
panel.render(controller.snapshot());
window.addEventListener(
  'pagehide',
  () => {
    panel.clearInputs();
    observe(() => controller.forget());
  },
  { once: true },
);
