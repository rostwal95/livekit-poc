/** Opt-in source-qualified communication history. Import starts no service. */
import { ChannelError } from './public-types.js';
import { NativeChannelInbox, NativeGateway, type NativeGatewayOptions } from './native.js';
import {
  SeededAccounts,
  type DatabaseSettings,
  type InboxHooks,
  type InboxObserver,
} from './postgres.js';
import {
  communicationConfig,
  communicationFields,
  type CommunicationIntegration,
  type ResponseAnchor,
  type SdkObservation,
  type BrowserObservation,
} from './communication-types.js';
export {
  createCommunicationIntegration,
  DEFAULT_COMMUNICATION_LIMITS,
  reduceCommunicationEvidence,
} from './communication-types.js';
export type {
  CommunicationGrant,
  CommunicationIntegration,
  CommunicationLimits,
  ResponseAnchor,
  BoundResponseAnchor,
  ResponseReceipt,
  SdkFact,
  SdkObservation,
  BrowserObservation,
  ObservationReceipt,
  StoredObservation,
  CommunicationProjection,
  ResponseView,
} from './communication-types.js';
export class CommunicationInbox extends NativeChannelInbox {
  constructor(
    database: DatabaseSettings,
    integration: CommunicationIntegration,
    accounts: SeededAccounts,
    hooks: InboxHooks = {},
    observer?: InboxObserver,
  ) {
    communicationConfig(integration);
    super(database, integration, accounts, hooks, observer);
  }
  beginResponse(token: string, input: ResponseAnchor) {
    return this.communicationBegin(token, input);
  }
  observeSdk(token: string, input: SdkObservation) {
    return this.communicationSdk(token, input);
  }
  observeBrowser(token: string, input: BrowserObservation) {
    return this.communicationBrowser(token, input);
  }
  inspectResponse(token: string, id: string) {
    return this.communicationInspect(token, id);
  }
  responses(token: string, query: Readonly<{ limit: number; beforeSequence?: string }>) {
    return this.communicationResponses(token, query);
  }
  observations(
    token: string,
    id: string,
    query: Readonly<{ limit: number; afterSequence?: string }>,
  ) {
    return this.communicationObservations(token, id, query);
  }
}
export class CommunicationGateway extends NativeGateway {
  constructor(options: NativeGatewayOptions) {
    let copied: Record<string, unknown>;
    try {
      copied = communicationFields(options, [
        'database',
        'integration',
        'accounts',
        'ports',
        ...(Reflect.ownKeys(options).includes('options') ? ['options'] : []),
      ]);
    } catch {
      throw new ChannelError('InvalidEvent');
    }
    communicationConfig(copied.integration as CommunicationIntegration);
    super(copied as NativeGatewayOptions);
  }
}
