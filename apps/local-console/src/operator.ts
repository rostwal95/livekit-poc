import './style.css';
import './operator.css';
import { mountBusinessPanel } from './business-panel';

const input = document.querySelector<HTMLInputElement>('#access-token')!;
const status = document.querySelector<HTMLElement>('#key-status')!;
let key = '';

function takeKey(): string {
  const entered = input.value.trim();
  if (entered) {
    key = entered;
    input.value = '';
    status.textContent = 'Key held for this page.';
  }
  if (!key) throw new Error('An operator key is required.');
  return key;
}

function forgetKey(): void {
  key = '';
  input.value = '';
  status.textContent = 'Operator key required.';
  business.forget();
}

const business = mountBusinessPanel(document.querySelector<HTMLElement>('#business')!, {
  takeToken: takeKey,
  heldToken: () => key,
  forgetToken: forgetKey,
  pollMilliseconds: 1200,
});

document.querySelector('#operator-key')!.addEventListener('submit', (event) => {
  event.preventDefault();
  try {
    takeKey();
    void business.resume().catch(() => undefined);
  } catch {
    input.focus();
  }
});
document.querySelector('#forget-key')!.addEventListener('click', forgetKey);
window.addEventListener('pagehide', forgetKey);
