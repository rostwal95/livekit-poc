import { ConnectionState, Room, RoomEvent, Track } from 'livekit-client';
import { LabController, LabInputError, MAX_REPLY_BYTES, MAX_TEXT_BYTES, appendBounded, readBoundedText } from './lab';
import type { RemoteParticipant } from 'livekit-client';
import type { Entry, EntryKind, LabState, RoomCallbacks, RoomPort } from './lab';
import { acceptAgentText, canUseAgentMedia, canControlMicrophone, isAgentSender, parseAudioDiagnostic } from './transport-policy';
import { assertReplay, IntakeError, nextDate, requestInvestigation, validateInvestigation, validateOperatorToken, canCorrectRejectedInput } from './intake';
import type { InvestigationInput, InvestigationReceipt } from './intake';
import { mountBusinessPanel } from './business-panel';
import type { BusinessPanelHandle } from './business-panel';
import { mountVoicePanel } from './voice-panel';
import type { VoicePanelHandle } from './voice-panel';
import './style.css';
import './workspace.css';

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) throw new Error('The application root is missing.');
app.innerHTML = `
  <a class="skip-link" href="#business-workspace">Skip to durable case workspace</a>
  <header class="masthead">
    <a class="brand" href="#playground" aria-label="Agents lab home"><img src="/vendor/livekit/lk-logo-dark.svg" alt="" width="30" height="30" /><span>Agents lab<span class="brand-sub">BUILT WITH LIVEKIT</span></span></a>
    <nav aria-label="Workspace"><a href="#business-workspace">Durable case</a><a href="#voice-workspace">Voice</a><a href="#diagnostics">Diagnostics</a><a href="#projects">Projects</a></nav>
    <span class="environment">LOCAL WORKSPACE</span>
  </header>
  <main class="shell">
    <section class="intro" id="playground" aria-labelledby="page-title">
      <div><p class="eyebrow">REALTIME AGENTS / LOCAL DEVELOPMENT</p><h1 id="page-title">Connect. Observe.<br class="mobile-break" /> Keep the context.</h1><p class="lede">Native voice, durable work and exact human confirmation.<br />A synthetic local case with persisted recovery evidence.</p></div>
      <div class="runtime-note"><span class="label">AGENT RUNTIME</span><span>Python Agents SDK</span><span class="runtime-caption">Voice profile · verified on join</span></div>
    </section>
    <p id="notice" class="notice" role="alert" hidden></p>
    <section class="panel operator-access" aria-labelledby="operator-access-title"><div class="operator-access-heading"><p class="eyebrow">SCOPED LOCAL ACCESS</p><h2 id="operator-access-title">One token. This page only.</h2><p>The shared token authorizes the business, native voice and diagnostic controls.</p></div><div class="operator-access-input">          <label for="access-token">Local operator token</label>
          <input id="access-token" name="access-token" type="password" autocomplete="off" spellcheck="false" placeholder="Paste your local token" />
          <p id="token-state" class="field-note">Held in memory only. Cleared by Forget or page reload.</p>
          <details class="token-help"><summary>Where do I find the token?</summary><code>python3.14 local-setup/stack.py token</code><p>Run from the repository root. Keep the output private.</p></details>
<button id="forget-token" class="text-button forget-token" type="button">Forget operator token</button></div></section>
    <section id="business-workspace"></section>
    <section id="voice-workspace"></section>
    <details class="diagnostics-panel" id="diagnostics"><summary>Transport diagnostics <span>Scripted echo and audio frame observations</span></summary>
    <div class="workspace">
      <section class="panel connection-panel" aria-labelledby="connection-title">
        <div class="panel-head"><span class="overline">CONFIGURATION</span><h2 id="connection-title">Your local session</h2></div>
        <form id="connect-form">
          <label for="room-name">Room name</label>
          <input id="room-name" name="room-name" type="text" value="lab-local" autocomplete="off" spellcheck="false" maxlength="52" pattern="lab-[a-z0-9][a-z0-9-]{0,47}" required />
          <button id="connect" type="submit" class="primary connect-button">Connect session</button>
        </form>
        <dl class="session-facts"><div><dt>Media server</dt><dd>Self-hosted LiveKit</dd></div><div><dt>Agent behavior</dt><dd>Text echo + audio diagnostics</dd></div><div><dt>Microphone</dt><dd>Off until you enable it</dd></div></dl>
      </section>
      <section class="panel activity-panel" aria-labelledby="activity-title">
        <div class="session-head"><div><span class="overline">LIVE TRANSPORT</span><h2 id="activity-title">Session activity</h2></div><span id="agent-state" class="agent-state">Agent offline</span><span id="connection-state" class="state" data-state="disconnected" role="status">Disconnected</span></div>
        <div class="activity-toolbar"><span>Text streams / audio observations</span><button id="clear-log" class="text-button" type="button">Clear activity</button></div>
        <div id="activity" class="activity" role="log" aria-live="polite" aria-relevant="additions"><div class="empty-state"><img src="/vendor/livekit/lk-logo-dark.svg" alt="" width="42" height="42" /><h3>Ready when you are.</h3><p>Connect a session, send a message,<br />and see the agent respond in real time.</p><span class="label">ACTUAL TRANSPORT. SCRIPTED RESPONSES.</span></div></div>
        <form id="message-form" class="message-form"><label class="sr-only" for="message">Message to the transport agent</label><input id="message" type="text" placeholder="Send a message to the agent…" autocomplete="off" disabled /><button id="send" type="submit" class="primary" disabled>Send</button></form>
        <div class="control-bar" aria-label="Session controls"><div class="microphone-control"><button id="microphone" type="button" class="secondary" aria-pressed="false" disabled>Enable microphone</button><span id="microphone-description">Microphone off</span></div><button id="disconnect" type="button" class="danger" disabled>End session</button></div>
      </section>
    </div>
    </details>
    <section id="continuity" class="continuity-section" aria-labelledby="continuity-title">
      <div class="section-heading"><div><p class="eyebrow">P1 / WORKING FOUNDATION</p><h2 id="continuity-title">One request. One durable identity.</h2><p>Retained M1 intake fixture: verify SQLite acceptance, safe replay and payload conflicts.</p></div><span class="badge">LIVE API + SQLITE</span></div>
      <div class="panel intake-panel">
        <form id="intake-form" class="intake-form">
          <div><label for="booking-reference">Synthetic booking</label><input id="booking-reference" value="DEMO-BK-001" maxlength="64" autocomplete="off" required /></div>
          <div><label for="check-in">Requested check-in</label><input id="check-in" type="date" value="2030-12-10" required /></div>
          <label class="confirmation" for="investigation-confirmed"><input id="investigation-confirmed" type="checkbox" required /><span>I confirm an investigation.<small>This does not authorize a booking change.</small></span></label>
          <button id="submit-intake" type="submit" class="primary">Submit investigation</button>
        </form>
        <ol class="intake-steps" aria-label="Observed intake transitions"><li id="step-confirm"><span class="step-index">01</span><div><strong>Explicit confirmation</strong><span>Investigation permission</span></div></li><li id="step-store"><span class="step-index">02</span><div><strong>Durable acceptance</strong><span>Acknowledged after persistence</span></div></li><li id="step-replay"><span class="step-index">03</span><div><strong>Identity preserved</strong><span>Same request, same task</span></div></li></ol>
        <div class="intake-result"><div id="intake-status" role="status" aria-live="polite"><strong>Ready to investigate.</strong><p>Use the operator token above. Confirmation is your explicit input; acceptance and replay are verified by the API.</p></div><p id="pending-identity" class="pending-identity" hidden></p><dl id="receipt" hidden><div><dt>Task</dt><dd id="task-id"></dd></div><div><dt>Request key</dt><dd id="request-key"></dd></div><div><dt>Execution</dt><dd>Queued · Worker recovery is planned</dd></div></dl></div>
        <div class="intake-actions"><button id="replay-intake" type="button" class="secondary" disabled>Replay same request</button><button id="conflict-intake" type="button" class="secondary" disabled>Test changed-payload conflict</button><button id="new-intake" type="button" class="text-button" disabled>New investigation</button></div>
        <p class="scope-note">This independent SQLite foundation proves intake, replay and conflict handling. Use the PostgreSQL case workspace above for managed inquiry execution, exact quote confirmation and recovery.</p>
      </div>
    </section>
    <section id="projects" class="projects-section" aria-labelledby="projects-title">
      <div class="section-heading"><div><p class="eyebrow">THE ECOSYSTEM</p><h2 id="projects-title">Three projects. Distinct proof.</h2><p>Each library has a small API, a failure story and its own acceptance gate.</p></div><a class="source-link" href="https://docs.livekit.io/frontends/agents-ui/" target="_blank" rel="noreferrer">LiveKit Agents UI reference</a></div>
      <div class="scope-grid">
        <article><div class="project-top"><span class="project-number">01 / P1</span><span class="badge">LOCAL WORKFLOW</span></div><h3>Agent Continuity Lab</h3><p>Work that survives the conversation.</p><details><summary>Implemented local demonstration</summary><ol><li>Accept an investigation and observe persisted work.</li><li>Confirm an exact supplier quote through explicit human input.</li><li>Inspect outcome, effect attempts and receiver delivery separately.</li></ol></details><span class="project-boundary">DURABLE EXECUTION</span></article>
        <article><div class="project-top"><span class="project-number">02 / P2</span><span class="badge">LOCAL SHOWCASE</span></div><h3>Channel Continuity Kit</h3><p>One case across voice, chat and SMS.</p><details><summary>Joined showcase demonstration</summary><ol><li>Ask by text or voice in a native agent session.</li><li>Leave, then follow up by simulated SMS on the same case.</li><li>Rejoin with the case and earlier messages restored.</li></ol></details><span class="project-boundary">CONVERSATION CONTINUITY</span></article>
        <article><div class="project-top"><span class="project-number">03 / P3</span><span class="badge">LOCAL SHOWCASE</span></div><h3>Delegation Reliability Kit</h3><p>Specialists that stay within the task.</p><details><summary>Joined showcase demonstration</summary><ol><li>Run the policy check as P1-issued background work.</li><li>Verify its facts before the result is recorded.</li><li>Show the result only while it applies to the case revision.</li></ol></details><span class="project-boundary">BOUNDED COLLABORATION</span></article>
      </div>
      <p class="scope-note">P2 and P3 run together in the separate joined showcase: <code>make channel-policy-demo-start</code>, then open 127.0.0.1:5179/channel-policy.html.</p>
    </section>
    <footer><span>Independent portfolio project · Built with LiveKit</span><span>P1 local workflow / P2 and P3 in the joined showcase</span></footer>
  </main>
`;

function element<T extends HTMLElement>(selector: string): T {
  const value = document.querySelector<T>(selector);
  if (!value) throw new Error('A required interface element is missing.');
  return value;
}
const accessToken = element<HTMLInputElement>('#access-token');
const roomName = element<HTMLInputElement>('#room-name');
const message = element<HTMLInputElement>('#message');
const connectButton = element<HTMLButtonElement>('#connect');
const disconnectButton = element<HTMLButtonElement>('#disconnect');
const microphoneButton = element<HTMLButtonElement>('#microphone');
const sendButton = element<HTMLButtonElement>('#send');
const notice = element<HTMLParagraphElement>('#notice');
const activity = element<HTMLDivElement>('#activity');
const tokenState = element<HTMLParagraphElement>('#token-state');
const lifetime = new AbortController();
let operatorToken = '';
let businessHandle: BusinessPanelHandle | null = null;
let voiceHandle: VoicePanelHandle | null = null;
let diagnosticHandle: LabController | null = null;
let forgetting = false;
let observedState: LabState = 'disconnected';
let transportAgentReady = false;
let sending = false;
let entries: Entry[] = [];
function announce(text: string): void { notice.textContent = text; notice.hidden = false; }
function forgetToken(): void {
  operatorToken = ''; accessToken.value = '';
  tokenState.textContent = 'Held in memory only. Cleared by Forget or page reload.';
  if (forgetting) return;
  forgetting = true;
  try { businessHandle?.forget(); voiceHandle?.forget(); if (diagnosticHandle && diagnosticHandle.state !== 'disconnected') void diagnosticHandle.disconnect().catch(() => undefined); } finally { forgetting = false; }
}
function takeToken(): string {
  const token = accessToken.value.trim() || operatorToken;
  validateOperatorToken(token);
  operatorToken = token; accessToken.value = '';
  tokenState.textContent = 'Operator token held in memory for this page.';
  return token;
}
function addEntry(kind: EntryKind, text: string): void {
  if (kind === 'error' && text.startsWith('Local access')) forgetToken();
  if (kind === 'diagnostic' && text === 'Diagnostic agent joined.') { element('#agent-state').textContent = 'Agent online'; transportAgentReady = true; syncMediaControls(); }
  if (kind === 'diagnostic' && text.startsWith('Diagnostic agent left')) { element('#agent-state').textContent = 'Agent offline'; transportAgentReady = false; syncMediaControls(); }
  entries = appendBounded(entries, { kind, text, time: new Date().toLocaleTimeString([], { hour12: false }) });
  activity.querySelector('.empty-state')?.remove();
  const row = document.createElement('div');
  row.className = `entry entry-${kind}`;
  const label = document.createElement('div'); label.className = 'entry-label';
  const title = document.createElement('span');
  title.textContent = ({ sent: 'YOU', received: 'AGENT', diagnostic: 'MEDIA', error: 'ERROR', system: 'SESSION' })[kind];
  const time = document.createElement('time'); time.textContent = entries.at(-1)!.time;
  label.append(title, time);
  const body = document.createElement('p'); body.textContent = text;
  row.append(label, body); activity.append(row);
  while (activity.children.length > 100) activity.firstElementChild?.remove();
  activity.scrollTop = activity.scrollHeight;
}
function syncMediaControls(): void {
  const ready = canUseAgentMedia(observedState, transportAgentReady);
  microphoneButton.disabled = !canControlMicrophone(observedState, transportAgentReady, microphoneButton.getAttribute('aria-pressed') === 'true'); message.disabled = !ready; sendButton.disabled = !ready || sending;
  message.placeholder = ready ? 'Send a message to the agent…' : observedState === 'connected' ? 'Waiting for the diagnostic agent…' : 'Connect a session to send a message…';
}
function updateState(state: LabState): void {
  observedState = state;
  if (['connecting', 'disconnected', 'error'].includes(state)) transportAgentReady = false;
  const indicator = element<HTMLSpanElement>('#connection-state');
  indicator.dataset.state = state;
  indicator.textContent = state.charAt(0).toUpperCase() + state.slice(1);
  const busy = ['connecting', 'disconnecting'].includes(state);
  const hasRoom = state === 'connected' || state === 'reconnecting';
  connectButton.disabled = busy || hasRoom;
  connectButton.textContent = state === 'connecting' ? 'Connecting…' : 'Connect session';
  connectButton.setAttribute('aria-busy', String(state === 'connecting'));
  disconnectButton.disabled = !busy && !hasRoom;
  syncMediaControls();
  roomName.disabled = busy || hasRoom;
  if (state === 'disconnected') element('#agent-state').textContent = 'Agent offline';
  if (state === 'connecting') element('#agent-state').textContent = 'Awaiting agent';
}
function createRoom(callbacks: RoomCallbacks): RoomPort {
  const room = new Room({ adaptiveStream: false, dynacast: false });
  const lifecycle = new AbortController();
  let activeReaders = 0, closing = false;
  const observedAgents = new Set<string>();
  const observeAgent = (participant: RemoteParticipant): void => {
    if (!isAgentSender(participant) || observedAgents.has(participant.identity)) return;
    observedAgents.add(participant.identity);
    callbacks.onDiagnostic('Diagnostic agent joined.');
  };
  const consume = (kind: 'text' | 'diagnostic'): Parameters<Room['registerTextStreamHandler']>[1] => (reader, info) => {
    const sender = room.remoteParticipants.get(info.identity);
    if (closing || activeReaders >= 4 || !isAgentSender(sender)) {
      void reader[Symbol.asyncIterator]().return().catch(() => undefined);
      return;
    }
    activeReaders += 1;
    void readBoundedText(
      reader.withAbortSignal(AbortSignal.any([lifecycle.signal, AbortSignal.timeout(10_000)])),
      kind === 'text' ? MAX_REPLY_BYTES : MAX_TEXT_BYTES,
    ).then((text) => {
      if (closing) return;
      if (kind === 'text') {
        const accepted = acceptAgentText(text, sender);
        if (accepted !== null) callbacks.onText(accepted);
      } else {
        const publication = [...room.localParticipant.audioTrackPublications.values()]
          .find((track) => track.source === Track.Source.Microphone && !track.isMuted);
        if (!publication) return;
        const diagnostic = parseAudioDiagnostic(text, sender, publication.trackSid);
        if (diagnostic !== null) callbacks.onDiagnostic(diagnostic);
      }
    }).catch(() => {
      if (!closing) callbacks.onDiagnostic('An incoming stream could not be read within the local contract.');
    }).finally(() => { activeReaders -= 1; });
  };
  room.registerTextStreamHandler('lk.agent.chat', consume('text'));
  room.registerTextStreamHandler('lk.agent.events', consume('diagnostic'));
  const cleanup = (): void => {
    closing = true; lifecycle.abort();
    room.unregisterTextStreamHandler('lk.agent.chat'); room.unregisterTextStreamHandler('lk.agent.events');
  };
  room.on(RoomEvent.ParticipantConnected, observeAgent);
  room.on(RoomEvent.ParticipantDisconnected, (participant) => {
    if (observedAgents.delete(participant.identity) && observedAgents.size === 0) callbacks.onDiagnostic('Diagnostic agent left. Reconnect or inspect the worker.');
  });
  room.on(RoomEvent.Disconnected, () => { cleanup(); callbacks.onDisconnected(); });
  room.on(RoomEvent.ConnectionStateChanged, (state) => {
    if (state === ConnectionState.Reconnecting) { callbacks.onReconnecting(); callbacks.onDiagnostic('Media connection is reconnecting.'); }
    else if (state === ConnectionState.Connected) callbacks.onReconnected();
  });
  return {
    connect: async (url, token) => {
      await room.connect(url, token, { rtcConfig: { iceServers: [] }, websocketTimeout: 10_000, peerConnectionTimeout: 10_000 });
      for (const participant of room.remoteParticipants.values()) observeAgent(participant);
    },
    disconnect: async () => { cleanup(); await room.disconnect(true); room.removeAllListeners(); },
    sendText: async (text) => { await room.localParticipant.sendText(text, { topic: 'lk.chat' }); },
    setMicrophoneEnabled: async (enabled) => { await room.localParticipant.setMicrophoneEnabled(enabled); },
  };
}
const controller = new LabController(createRoom, {
  onState: updateState, onEntry: addEntry,
  onMicrophone: (enabled) => {
    microphoneButton.setAttribute('aria-pressed', String(enabled));
    microphoneButton.textContent = enabled ? 'Mute microphone' : 'Enable microphone';
    element<HTMLSpanElement>('#microphone-description').textContent = enabled ? 'Publishing · Agent reports received frames' : 'Microphone off';
    syncMediaControls();
  },
});
diagnosticHandle = controller;
element<HTMLFormElement>('#connect-form').addEventListener('submit', (event) => {
  event.preventDefault(); notice.hidden = true;
  try {
    const secret = takeToken();
    void controller.connect({ room: roomName.value.trim(), identity: `browser-${crypto.randomUUID().slice(0, 12)}`, dispatch_agent: true }, secret)
      .catch(() => announce('Unable to begin a local connection.'));
  } catch (error) { announce(error instanceof LabInputError ? error.message : 'Enter the local operator token.'); }
});
disconnectButton.addEventListener('click', () => { void controller.disconnect().catch(() => announce('The room was closed with a cleanup error.')); });
element<HTMLButtonElement>('#forget-token').addEventListener('click', forgetToken);
microphoneButton.addEventListener('click', () => {
  microphoneButton.disabled = true;
  void controller.toggleMicrophone().catch(() => announce('Microphone publishing could not be enabled. Check browser permission and reconnect if needed.'))
    .finally(syncMediaControls);
});
element<HTMLFormElement>('#message-form').addEventListener('submit', (event) => {
  event.preventDefault(); if (sending) return;
  sending = true; sendButton.disabled = true;
  void controller.send(message.value).then(() => { message.value = ''; }).catch((error: unknown) => {
    announce(error instanceof LabInputError ? error.message : 'Message delivery failed. This transport lab does not promise durable message delivery.');
  }).finally(() => { sending = false; sendButton.disabled = !canUseAgentMedia(controller.state, transportAgentReady); });
});
element<HTMLButtonElement>('#clear-log').addEventListener('click', () => { entries = []; activity.replaceChildren(); });

const booking = element<HTMLInputElement>('#booking-reference');
const checkIn = element<HTMLInputElement>('#check-in');
const confirmation = element<HTMLInputElement>('#investigation-confirmed');
const submitIntake = element<HTMLButtonElement>('#submit-intake');
const replayIntake = element<HTMLButtonElement>('#replay-intake');
const conflictIntake = element<HTMLButtonElement>('#conflict-intake');
const newIntake = element<HTMLButtonElement>('#new-intake');
const intakeStatus = element<HTMLDivElement>('#intake-status');
let snapshot: InvestigationInput | undefined;
let receipt: InvestigationReceipt | undefined;
let intakeBusy = false;
let unacknowledgedAttempt = false;
function intakeMessage(title: string, description: string, state: string): void {
  const heading = document.createElement('strong'); heading.textContent = title;
  const body = document.createElement('p'); body.textContent = description;
  intakeStatus.replaceChildren(heading, body); intakeStatus.dataset.state = state;
}
function step(selector: string, complete: boolean): void { element(selector).dataset.complete = String(complete); }
function updateIntakeControls(): void {
  submitIntake.disabled = intakeBusy || receipt !== undefined;
  submitIntake.textContent = intakeBusy ? 'Checking durable state…' : receipt ? 'Investigation stored' : snapshot ? 'Retry same investigation' : 'Submit investigation';
  submitIntake.setAttribute('aria-busy', String(intakeBusy));
  replayIntake.disabled = intakeBusy || !receipt;
  conflictIntake.disabled = intakeBusy || !receipt;
  newIntake.disabled = intakeBusy || !receipt;
  for (const field of [booking, checkIn, confirmation]) field.disabled = intakeBusy || snapshot !== undefined;
}
async function intakeAction(action: 'submit' | 'replay' | 'conflict'): Promise<void> {
  if (intakeBusy) return;
  try {
    const secret = takeToken();
    if (!snapshot) {
      const candidate = { booking_reference: booking.value.trim().toUpperCase(), new_check_in: checkIn.value, confirmed: confirmation.checked, idempotency_key: `showcase-${crypto.randomUUID()}` };
      validateInvestigation(candidate); snapshot = candidate;
    }
    const request = snapshot;
    const pendingIdentity = element<HTMLParagraphElement>('#pending-identity');
    pendingIdentity.textContent = 'Request key: ' + request.idempotency_key + '. Retain this identity if the acknowledgement is lost.';
    pendingIdentity.hidden = receipt !== undefined;
    step('#step-confirm', true);
    intakeBusy = true; updateIntakeControls();
    intakeMessage(action === 'submit' ? 'Awaiting durable acknowledgement…' : action === 'replay' ? 'Replaying the original request…' : 'Checking conflict protection…', 'Progress is updated only after the API confirms its outcome.', 'pending');
    if (action === 'conflict') {
      const original = receipt;
      if (!original) throw new LabInputError('Submit an investigation first.');
      try {
        await requestInvestigation({ ...request, new_check_in: nextDate(request.new_check_in) }, secret, lifetime.signal);
        throw new IntakeError('unknown', 'The changed payload was unexpectedly accepted. Inspect the original task before continuing.');
      } catch (error) { if (!(error instanceof IntakeError) || error.code !== 'conflict') throw error; }
      const recovered = await requestInvestigation(request, secret, lifetime.signal);
      assertReplay(original, recovered);
      step('#step-replay', true);
      intakeMessage('Conflict rejected. Original request intact.', 'The changed date returned a conflict. Replaying the original verified the same task and original payload.', 'verified');
      return;
    }
    const result = await requestInvestigation(request, secret, lifetime.signal);
    if (receipt) assertReplay(receipt, result);
    receipt = result;
    unacknowledgedAttempt = false;
    step('#step-store', true);
    step('#step-replay', !result.created);
    element('#pending-identity').hidden = true;
    element('#receipt').hidden = false;
    element('#task-id').textContent = result.task.task_id;
    element('#request-key').textContent = result.task.idempotency_key;
    intakeMessage(result.created ? 'Accepted and stored.' : 'Replay verified. Same durable identity.', result.created ? 'The investigation is queued in SQLite. Replay it to verify deduplication; execution is a future milestone.' : 'The original task was returned. No second logical investigation was created.', result.created ? 'stored' : 'verified');
  } catch (error) {
    if (canCorrectRejectedInput(error, unacknowledgedAttempt) && !receipt) { snapshot = undefined; element('#pending-identity').hidden = true; }
    if (error instanceof IntakeError && error.code === 'unknown') unacknowledgedAttempt = true;
    if (error instanceof IntakeError && error.code === 'unauthorized') forgetToken();
    intakeMessage(error instanceof IntakeError && error.code === 'unknown' ? 'Outcome needs reconciliation.' : 'Request needs attention.', error instanceof IntakeError || error instanceof LabInputError ? error.message : 'The acknowledgement could not be verified. Retry with the same request identity.', 'error');
  } finally { intakeBusy = false; updateIntakeControls(); }
}
element<HTMLFormElement>('#intake-form').addEventListener('submit', (event) => { event.preventDefault(); void intakeAction('submit'); });
replayIntake.addEventListener('click', () => { void intakeAction('replay'); });
conflictIntake.addEventListener('click', () => { void intakeAction('conflict'); });
newIntake.addEventListener('click', () => {
  if (intakeBusy || !receipt) return;
  snapshot = undefined; receipt = undefined; unacknowledgedAttempt = false; element('#receipt').hidden = true; element('#pending-identity').hidden = true;
  confirmation.checked = false;
  for (const selector of ['#step-confirm', '#step-store', '#step-replay']) step(selector, false);
  intakeMessage('Ready for a new investigation.', 'Previously accepted tasks remain stored. This only resets the form.', 'idle');
  updateIntakeControls();
});
businessHandle = mountBusinessPanel(element('#business-workspace'), { takeToken, forgetToken, signal: lifetime.signal, onTask: () => voiceHandle?.forget() });
voiceHandle = mountVoicePanel(element('#voice-workspace'), { takeToken, forgetToken, getTaskId: () => businessHandle?.getCurrentTask() ?? null, observeTask: async (taskId) => { await businessHandle?.observeTask(taskId); }, signal: lifetime.signal });
window.addEventListener('pagehide', () => { forgetToken(); lifetime.abort(); businessHandle?.dispose(); voiceHandle?.dispose(); void controller.disconnect().catch(() => undefined); }, { once: true });
