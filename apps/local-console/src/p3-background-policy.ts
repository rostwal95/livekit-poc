/** P3 conversation ownership. Only validated observations enter this controller. */
export type BackgroundCode =
  | 'invalid'
  | 'access_denied'
  | 'unavailable'
  | 'unknown'
  | 'overloaded'
  | 'closed'
  | 'cleanup_incomplete';
export class BackgroundError extends Error {
  constructor(readonly code: BackgroundCode) {
    super(code);
  }
}
export type BackgroundPhase =
  | 'idle'
  | 'joining'
  | 'connected'
  | 'reconnecting'
  | 'ending'
  | 'cleanup_incomplete'
  | 'disconnected';
export type BackgroundMessage = Readonly<{
  id: number;
  role: 'user' | 'agent';
  text: string;
  delivery: 'sending' | 'sent' | 'unknown' | 'received';
}>;
export interface BackgroundIdentity {
  readonly sessionId: string;
  readonly caseId: string;
  readonly delegationId: string;
  readonly requestRevision: number;
  readonly inputFingerprint: string;
}
export interface BackgroundState<T> {
  readonly identity: BackgroundIdentity | null;
  readonly phase: BackgroundPhase;
  readonly ready: boolean;
  readonly code: BackgroundCode | null;
  readonly ownedClient: 0 | 1;
  readonly actualRequests: 0 | 1;
  readonly actualSends: 0 | 1;
  readonly observation: T | null;
  readonly historical: boolean;
  readonly reading: boolean;
  readonly messages: readonly BackgroundMessage[];
  readonly cleanupComplete: boolean;
}
export interface BackgroundCallbacks {
  session?(value: BackgroundIdentity): void;
  ready(value: boolean): void;
  text(value: string): void;
  connection(value: 'reconnecting' | 'connected' | 'disconnected'): void;
}
/** Construction is inert. close resolves only after the port's actual owned I/O settles. */
export interface BackgroundPort<T> {
  join(signal: AbortSignal): Promise<void>;
  sendText(text: string): Promise<void>;
  read(signal: AbortSignal): Promise<T>;
  clearCredential(): void;
  close(): Promise<void>;
}
export type BackgroundFactory<T> = (
  token: string,
  callbacks: BackgroundCallbacks,
) => BackgroundPort<T>;
export const BACKGROUND_LIMITS = Object.freeze({
  messageBytes: 4096,
  agentBytes: 16384,
  messages: 32,
  transcriptBytes: 65536,
  joinMs: 10000,
  sendMs: 8000,
  readMs: 4000,
  closeMs: 5000,
});
interface Owner<T> {
  readonly epoch: number;
  readonly abort: AbortController;
  readonly work: Set<Promise<void>>;
  readonly constructed: Promise<void>;
  port: BackgroundPort<T> | null;
  closing: boolean;
  readAbort: AbortController | null;
  closePass: Promise<void> | null;
  closeView: Promise<void> | null;
}
const encoder = new TextEncoder();
function initial<T>(): BackgroundState<T> {
  return Object.freeze({
    identity: null,
    phase: 'idle',
    ready: false,
    code: null,
    ownedClient: 0,
    actualRequests: 0,
    actualSends: 0,
    observation: null,
    historical: false,
    reading: false,
    messages: Object.freeze([]),
    cleanupComplete: true,
  });
}
export function safeBackgroundCode(error: unknown, fallback: BackgroundCode): BackgroundCode {
  if (error instanceof BackgroundError) {
    const value: unknown = Object.getOwnPropertyDescriptor(error, 'code')?.value;
    if (
      typeof value === 'string' &&
      [
        'invalid',
        'access_denied',
        'unavailable',
        'unknown',
        'overloaded',
        'closed',
        'cleanup_incomplete',
      ].includes(value)
    )
      return value as BackgroundCode;
  }
  return fallback;
}
function observe<T>(
  actual: Promise<T>,
  milliseconds: number,
  code: BackgroundCode,
  abandon?: () => void,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      abandon?.();
      reject(new BackgroundError(code));
    }, milliseconds);
    actual.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}
export class BackgroundController<T> {
  #state: BackgroundState<T> = initial<T>();
  #owner: Owner<T> | null = null;
  #epoch = 0;
  #message = 0;
  constructor(
    readonly factory: BackgroundFactory<T>,
    readonly changed: (state: BackgroundState<T>) => void,
    readonly readError: (value: T) => BackgroundCode | null = () => null,
  ) {}
  snapshot(): BackgroundState<T> {
    return this.#state;
  }
  #publish(update: Partial<BackgroundState<T>>): void {
    this.#state = Object.freeze({ ...this.#state, ...update });
    try {
      this.changed(this.#state);
    } catch {
      /* Presentation cannot release a resource reservation. */
    }
  }
  #current(owner: Owner<T>): boolean {
    return this.#owner === owner && owner.epoch === this.#epoch && !owner.closing;
  }
  #track<R>(owner: Owner<T>, operation: () => Promise<R>): Promise<R> {
    let release!: () => void;
    const completion = new Promise<void>((resolve) => {
      release = resolve;
    });
    owner.work.add(completion); // Reserve before invoking application/native code.
    let actual: Promise<R>;
    try {
      actual = Promise.resolve(operation());
    } catch (error) {
      actual = Promise.reject(error);
    }
    actual.then(
      () => {
        owner.work.delete(completion);
        release();
      },
      () => {
        owner.work.delete(completion);
        release();
      },
    );
    return actual;
  }
  #append(message: BackgroundMessage): void {
    const rows = [...this.#state.messages, Object.freeze(message)];
    let bytes = rows.reduce((total, row) => total + encoder.encode(row.text).byteLength, 0);
    while (rows.length > BACKGROUND_LIMITS.messages || bytes > BACKGROUND_LIMITS.transcriptBytes) {
      const removed = rows.shift();
      if (removed) bytes -= encoder.encode(removed.text).byteLength;
    }
    this.#publish({ messages: Object.freeze(rows) });
  }
  #delivery(id: number, delivery: BackgroundMessage['delivery']): void {
    this.#publish({
      messages: Object.freeze(
        this.#state.messages.map((row) =>
          row.id === id ? Object.freeze({ ...row, delivery }) : row,
        ),
      ),
    });
  }
  async connect(token: string): Promise<void> {
    if (this.#owner) throw new BackgroundError('overloaded');
    if (!token || encoder.encode(token).byteLength > 8192) throw new BackgroundError('invalid');
    let constructed!: () => void;
    const construction = new Promise<void>((resolve) => {
      constructed = resolve;
    });
    const owner: Owner<T> = {
      epoch: ++this.#epoch,
      abort: new AbortController(),
      work: new Set(),
      constructed: construction,
      port: null,
      closing: false,
      readAbort: null,
      closePass: null,
      closeView: null,
    };
    this.#owner = owner;
    this.#publish({ ...initial<T>(), phase: 'joining', ownedClient: 1, cleanupComplete: false });
    try {
      if (owner.closing) throw new BackgroundError('closed');
      try {
        owner.port = this.factory(token, {
          session: (value) => {
            if (this.#current(owner)) this.#publish({ identity: Object.freeze({ ...value }) });
          },
          ready: (value) => {
            if (this.#current(owner)) this.#publish({ ready: value });
          },
          text: (value) => {
            if (
              this.#current(owner) &&
              value.length > 0 &&
              encoder.encode(value).byteLength <= BACKGROUND_LIMITS.agentBytes
            )
              this.#append({
                id: ++this.#message,
                role: 'agent',
                text: value,
                delivery: 'received',
              });
          },
          connection: (value) => {
            if (!this.#current(owner)) return;
            if (value === 'disconnected') {
              this.#publish({ ready: false });
              void this.end().catch(() => undefined);
            } else this.#publish({ phase: value, ready: false });
          },
        });
      } finally {
        constructed();
      }
      if (owner.closing) throw new BackgroundError('closed');
      await observe(
        this.#track(owner, () => owner.port!.join(owner.abort.signal)),
        BACKGROUND_LIMITS.joinMs,
        'unavailable',
        () => owner.abort.abort(),
      );
      if (this.#current(owner)) this.#publish({ phase: 'connected', code: null });
    } catch (error) {
      constructed();
      if (this.#current(owner)) {
        const code = safeBackgroundCode(error, 'unavailable');
        this.#publish({ code });
        try {
          await this.end();
        } catch {
          /* Retain the first join error and the actual owner. */
        }
        this.#publish({ code });
      }
      throw new BackgroundError(safeBackgroundCode(error, 'unavailable'));
    }
  }
  async send(text: string): Promise<void> {
    const owner = this.#owner;
    if (
      !owner ||
      !this.#current(owner) ||
      this.#state.phase !== 'connected' ||
      this.#state.code === 'access_denied' ||
      !this.#state.ready
    )
      throw new BackgroundError('closed');
    if (this.#state.actualSends) throw new BackgroundError('overloaded');
    if (!text.trim() || encoder.encode(text).byteLength > BACKGROUND_LIMITS.messageBytes)
      throw new BackgroundError('invalid');
    const id = ++this.#message;
    this.#publish({ actualSends: 1, code: null });
    if (!this.#current(owner)) {
      if (this.#owner === owner) this.#publish({ actualSends: 0 });
      throw new BackgroundError('closed');
    }
    this.#append({ id, role: 'user', text, delivery: 'sending' });
    if (!this.#current(owner)) {
      if (this.#owner === owner) this.#publish({ actualSends: 0 });
      throw new BackgroundError('closed');
    }
    const actual = this.#track(owner, () => owner.port!.sendText(text));
    actual.then(
      () => {
        if (this.#owner === owner) this.#publish({ actualSends: 0 });
        if (this.#current(owner)) this.#delivery(id, 'sent');
      },
      () => {
        if (this.#owner === owner) this.#publish({ actualSends: 0 });
        if (this.#current(owner)) this.#delivery(id, 'unknown');
      },
    );
    try {
      await observe(actual, BACKGROUND_LIMITS.sendMs, 'unknown');
    } catch (error) {
      if (this.#current(owner)) {
        this.#delivery(id, 'unknown');
        this.#publish({ code: safeBackgroundCode(error, 'unknown') });
      }
      throw new BackgroundError(safeBackgroundCode(error, 'unknown'));
    }
  }
  async refresh(): Promise<void> {
    const owner = this.#owner;
    if (
      !owner ||
      !this.#current(owner) ||
      this.#state.phase !== 'connected' ||
      this.#state.code === 'access_denied'
    )
      throw new BackgroundError('closed');
    if (this.#state.actualRequests) throw new BackgroundError('overloaded');
    const abort = new AbortController();
    owner.readAbort = abort;
    this.#publish({ actualRequests: 1, reading: true, code: null });
    if (!this.#current(owner)) {
      if (owner.readAbort === abort) owner.readAbort = null;
      if (this.#owner === owner) this.#publish({ actualRequests: 0, reading: false });
      throw new BackgroundError('closed');
    }
    const actual = this.#track(owner, () => owner.port!.read(abort.signal));
    actual.then(
      () => {
        if (this.#owner === owner) this.#publish({ actualRequests: 0 });
      },
      () => {
        if (this.#owner === owner) this.#publish({ actualRequests: 0 });
      },
    );
    try {
      const value = await observe(actual, BACKGROUND_LIMITS.readMs, 'unavailable', () =>
        abort.abort(),
      );
      if (this.#current(owner)) {
        const code = this.readError(value);
        this.#publish({
          observation: code ? (this.#state.observation ?? value) : value,
          historical: code !== null && this.#state.observation !== null,
          code,
        });
      }
    } catch (error) {
      if (this.#current(owner))
        this.#publish({
          historical: this.#state.observation !== null,
          code: safeBackgroundCode(error, 'unavailable'),
        });
      throw new BackgroundError(safeBackgroundCode(error, 'unavailable'));
    } finally {
      if (owner.readAbort === abort) owner.readAbort = null;
      if (this.#current(owner)) this.#publish({ reading: false });
    }
  }
  end(): Promise<void> {
    return this.#close(false);
  }
  forget(): Promise<void> {
    return this.#close(true);
  }
  #close(forget: boolean): Promise<void> {
    const owner = this.#owner;
    const firstClose = owner !== null && !owner.closing;
    // Fence admission and callbacks before aborts, credential callbacks or presentation.
    if (owner && firstClose) {
      owner.closing = true;
      ++this.#epoch;
      owner.abort.abort();
      owner.readAbort?.abort();
      try {
        owner.port?.clearCredential();
      } catch {
        /* Actual close remains required. */
      }
    }
    const clearPrivate =
      forget &&
      (this.#state.identity !== null ||
        this.#state.observation !== null ||
        this.#state.messages.length > 0 ||
        this.#state.code !== null);
    if (firstClose || clearPrivate) {
      this.#publish({
        ...(firstClose
          ? {
              phase: 'ending' as const,
              ready: false,
              reading: false,
              historical: this.#state.observation !== null,
            }
          : {}),
        ...(forget
          ? {
              identity: null,
              observation: null,
              historical: false,
              messages: Object.freeze([]),
              code: null,
            }
          : {}),
      });
    }
    if (!owner) {
      if (
        this.#state.phase !== 'idle' ||
        this.#state.ready ||
        this.#state.reading ||
        !this.#state.cleanupComplete
      )
        this.#publish({ phase: 'idle', ready: false, reading: false, cleanupComplete: true });
      return Promise.resolve();
    }
    if (owner.closeView) return owner.closeView;
    if (!owner.closePass) {
      const pass = owner.constructed
        .then(async () => {
          let portClose: Promise<void>;
          try {
            portClose = Promise.resolve(owner.port?.close());
          } catch {
            portClose = Promise.reject(new BackgroundError('cleanup_incomplete'));
          }
          return await Promise.allSettled([portClose, ...owner.work]);
        })
        .then((outcomes) => {
          if (outcomes.some((outcome) => outcome.status === 'rejected'))
            throw new BackgroundError('cleanup_incomplete');
          if (this.#owner === owner) {
            this.#owner = null;
            this.#publish({
              phase: 'disconnected',
              ownedClient: 0,
              actualRequests: 0,
              actualSends: 0,
              cleanupComplete: true,
              code: null,
            });
          }
        });
      owner.closePass = pass;
      void pass.catch(() => {
        if (owner.closePass === pass) owner.closePass = null;
      });
    }
    const view = observe(owner.closePass, BACKGROUND_LIMITS.closeMs, 'cleanup_incomplete')
      .catch(() => {
        if (this.#owner === owner)
          this.#publish({
            phase: 'cleanup_incomplete',
            code: 'cleanup_incomplete',
            cleanupComplete: false,
          });
        throw new BackgroundError('cleanup_incomplete');
      })
      .finally(() => {
        if (owner.closeView === view) owner.closeView = null;
      });
    owner.closeView = view;
    return view;
  }
}
