/** Accessible native voice surface; the business panel retains consent authority. */
import { createNativeVoiceRoom, nativeSessionReady, voiceInferenceLabel, VoiceController } from './voice';
import type { VoiceState, VoiceInputSource } from './voice';
import './voice.css';

export interface VoicePanelOptions {
  readonly takeToken: () => string;
  readonly forgetToken: () => void;
  readonly getTaskId: () => string | null;
  readonly observeTask: (taskId: string) => Promise<void>;
  readonly signal?: AbortSignal;
}
export interface VoicePanelHandle { forget(): void; dispose(): void }
export function mountVoicePanel(host: HTMLElement, options: VoicePanelOptions): VoicePanelHandle {
  host.classList.add('voice-section');
  host.setAttribute('aria-labelledby', 'voice-title');
  host.innerHTML = `
    <div class="section-heading"><div><p class="eyebrow">P1 / NATIVE AGENTSESSION</p><h2 id="voice-title">A conversation can end. The work continues.</h2><p>Join the loaded durable task through LiveKit. Voice observations and business consent stay separate.</p></div><span id="voice-profile" class="badge">LOCAL VOICE · JOIN TO VERIFY PROFILE</span></div>
    <div class="voice-layout">
      <section class="panel voice-controls" aria-labelledby="voice-controls-title"><div class="panel-head"><span class="overline">NATIVE REALTIME SESSION</span><h3 id="voice-controls-title">Speak with the local agent</h3></div>
        <div class="voice-body"><label for="voice-input-source">Audio input source</label><select id="voice-input-source"><option value="scripted" selected>Prerecorded local WAV · no microphone access</option><option value="microphone">Physical microphone · browser permission required</option></select><p class="business-explanation">The default publishes a local audio fixture through WebAudio and native WebRTC. It does not access your microphone.</p><p id="voice-task" class="business-mono">Load a verified durable case above before joining.</p><div class="voice-join"><button id="voice-connect" class="primary" type="button">Join local voice</button><button id="voice-end" class="danger" type="button" disabled>End voice session</button></div>
        <p id="voice-status" class="voice-status" role="status" aria-live="polite">Load a durable case, then explicitly join its local voice session.</p>
        <dl class="voice-facts"><div><dt>Room connection</dt><dd id="voice-connection">Disconnected</dd></div><div><dt>Native agent state</dt><dd id="voice-speech">Unknown</dd></div><div><dt>Browser playback</dt><dd id="voice-playback">Unavailable</dd></div><div><dt>Manual input turn</dt><dd id="voice-turn">Idle</dd></div></dl>
        <div class="voice-microphone"><button id="voice-microphone" class="secondary" type="button" aria-pressed="false" disabled>Enable voice microphone</button><span id="voice-microphone-state">Microphone off</span></div>
        <div class="voice-turn-controls" aria-label="Manual voice input"><button id="voice-start" class="secondary" type="button" disabled>Start input turn</button><button id="voice-commit" class="primary" type="button" disabled>Commit input turn</button><button id="voice-interrupt" class="secondary" type="button" disabled>Interrupt speech</button></div>
        <div class="voice-other-controls"><button id="voice-status-request" class="text-button" type="button" disabled>Ask case status via native text</button><button id="voice-enable-playback" class="text-button" type="button" disabled>Enable browser playback</button></div>
        <p class="business-explanation">Choose a source before joining, then publish it explicitly. Start and commit a manual turn through the configured native profile. Interrupt and End voice affect the conversation; use the separate business control to request cancellation.</p>
        </div>
      </section>
      <section class="panel voice-output" aria-labelledby="voice-output-title"><div class="panel-head"><span class="overline">OBSERVED OUTPUT</span><h3 id="voice-output-title">Speech and scoped continuity</h3></div><div class="voice-body"><p class="business-explanation">Agent state comes from the native participant. Audio playback comes from browser media events. Received task hints trigger an authenticated case refresh; they never carry authoritative progress.</p><div id="voice-audio" class="voice-audio" aria-label="Native agent audio players"></div><ol id="voice-transcripts" class="voice-transcripts" aria-label="Native agent transcriptions" aria-live="polite" aria-relevant="additions"><li class="voice-empty">No agent transcription has been received.</li></ol><details class="business-technical"><summary>Media identity and page transport counters</summary><pre id="voice-identity">No native room joined.</pre></details></div></section>
    </div>`;
  const owned = new AbortController(); let disposed = false, priorEntries: readonly string[] | null = null, tokenDenied = false;
  function element<T extends HTMLElement>(selector: string): T { const value = host.querySelector<T>(selector); if (!value) throw new Error('A voice interface element is missing.'); return value; }
  const button = (selector: string): HTMLButtonElement => element<HTMLButtonElement>(selector);
  const text = (selector: string, value: string): void => { element(selector).textContent = value; };
  const title = (value: string): string => value.replaceAll('_', ' ').replace(/^./, (first) => first.toUpperCase());
  function render(state: VoiceState): void {
    if (disposed) return;
    const scripted = (['connecting', 'connected', 'reconnecting', 'disconnecting'].includes(state.connection) ? state.input_source : element<HTMLSelectElement>('#voice-input-source').value) === 'scripted';
    const busy = ['connecting', 'disconnecting'].includes(state.connection), roomPresent = ['connected', 'reconnecting'].includes(state.connection), ready = nativeSessionReady(state);
    const profile = voiceInferenceLabel(state.inference_mode);
    text('#voice-profile', state.inference_mode === null ? profile : `${ready ? 'NATIVE PROFILE MATCHED' : 'CONFIGURED PROFILE'} · ${profile}`);
    element('#voice-profile').dataset.inferenceMode = state.inference_mode ?? 'unconfigured';
    element('#voice-profile').dataset.profileState = state.inference_mode === null ? 'unconfigured' : ready ? 'matched' : 'configured';
    text('#voice-status', state.message); text('#voice-task', state.task_id ? `Durable task: ${state.task_id}` : 'Load a verified durable case above before joining.');
    text('#voice-connection', title(state.connection)); text('#voice-speech', state.agent_id ? title(state.speech) : 'Agent absent'); text('#voice-playback', title(state.playback)); text('#voice-turn', title(state.turn));
    element('#voice-status').dataset.state = state.connection;
    element<HTMLSelectElement>('#voice-input-source').disabled = busy || roomPresent || state.microphone_uncertain;
    button('#voice-connect').disabled = busy || roomPresent || state.microphone_uncertain; button('#voice-connect').textContent = state.connection === 'connecting' ? 'Joining…' : 'Join local voice';
    button('#voice-end').disabled = !busy && !roomPresent; button('#voice-end').textContent = state.connection === 'disconnecting' ? 'Ending voice…' : 'End voice session';
    button('#voice-microphone').disabled = state.microphone_busy || (state.microphone || state.microphone_uncertain ? !roomPresent : !ready);
    button('#voice-microphone').setAttribute('aria-pressed', String(state.microphone || state.microphone_uncertain)); button('#voice-microphone').textContent = state.microphone || state.microphone_uncertain ? scripted ? 'Stop prerecorded input' : 'Mute voice microphone' : scripted ? 'Publish prerecorded input' : 'Enable voice microphone';
    text('#voice-microphone-state', state.microphone_busy ? 'Updating audio input…' : state.microphone_uncertain ? 'Audio input state unconfirmed — stop or end voice' : state.microphone ? scripted ? 'Prerecorded input publishing' : 'Publishing microphone' : scripted ? 'Prerecorded input stopped' : 'Microphone off');
    button('#voice-start').disabled = !ready || (!state.microphone || state.microphone_uncertain) || state.rpc_busy || state.interrupt_busy || state.turn === 'capturing';
    button('#voice-commit').disabled = !ready || state.rpc_busy || state.interrupt_busy || state.turn !== 'capturing';
    button('#voice-interrupt').disabled = !ready || state.interrupt_busy;
    button('#voice-status-request').disabled = !ready || state.status_busy;
    button('#voice-enable-playback').disabled = !roomPresent || state.playback_busy;
    text('#voice-identity', JSON.stringify({ task_id: state.task_id, room: state.room, agent_identity: state.agent_id, mode: state.inference_mode, profile_configured: state.inference_mode !== null, profile_verified: ready, input_source: state.input_source, connected: state.connection === 'connected', room_io_ready: state.session_ready, agent_present: state.agent_id !== null, session_ready: nativeSessionReady(state), displayed_transcripts: state.entries.length, text_diagnostics: state.text_diagnostics, business_cancellation: 'Separate explicit HTTP command' }, null, 2));
    if (priorEntries !== state.entries) {
      priorEntries = state.entries;
      const list = element<HTMLOListElement>('#voice-transcripts');
      if (state.entries.length) { const rows = state.entries.map((entry) => { const row = document.createElement('li'); row.textContent = entry; return row; }); list.replaceChildren(...rows); list.scrollTop = list.scrollHeight; }
      else { const row = document.createElement('li'); row.className = 'voice-empty'; row.textContent = 'No agent transcription has been received.'; list.replaceChildren(row); }
    }
  }
  const controller = new VoiceController((callbacks, source, mode) => createNativeVoiceRoom(callbacks, element('#voice-audio'), source, mode), render, options.observeTask);
  function run(action: () => Promise<void>): void { void action().catch(() => { if (!disposed) text('#voice-status', 'The local voice action was not acknowledged. Inspect the scoped case; its business state remains independent.'); }); }
  button('#voice-connect').addEventListener('click', () => {
    const task = options.getTaskId();
    if (!task) { text('#voice-status', 'Submit or resume a verified durable task above before joining local voice.'); return; }
    let token: string; try { token = options.takeToken(); } catch { text('#voice-status', 'Enter the local operator token before joining local voice.'); return; }
    tokenDenied = false;
    run(async () => { await controller.connect(task, token, element<HTMLSelectElement>('#voice-input-source').value as VoiceInputSource); if (controller.state.connection === 'error' && controller.state.message.startsWith('Operator access was denied') && !tokenDenied) { tokenDenied = true; options.forgetToken(); } });
  }, { signal: owned.signal });
  button('#voice-end').addEventListener('click', () => run(() => controller.disconnect()), { signal: owned.signal });
  button('#voice-microphone').addEventListener('click', () => run(() => controller.microphone(!(controller.state.microphone || controller.state.microphone_uncertain))), { signal: owned.signal });
  button('#voice-start').addEventListener('click', () => run(() => controller.turn('start')), { signal: owned.signal });
  button('#voice-commit').addEventListener('click', () => run(() => controller.turn('commit')), { signal: owned.signal });
  button('#voice-interrupt').addEventListener('click', () => run(() => controller.interrupt()), { signal: owned.signal });
  button('#voice-status-request').addEventListener('click', () => run(() => controller.status()), { signal: owned.signal });
  button('#voice-enable-playback').addEventListener('click', () => run(() => controller.enablePlayback()), { signal: owned.signal });
  element<HTMLSelectElement>('#voice-input-source').addEventListener('change', () => render(controller.state), { signal: owned.signal });
  render(controller.state);
  const handle: VoicePanelHandle = { forget: () => controller.forget(), dispose: () => { if (disposed) return; disposed = true; owned.abort(); void controller.dispose(); } };
  options.signal?.addEventListener('abort', handle.dispose, { once: true }); if (options.signal?.aborted) handle.dispose();
  return handle;
}
