/**
 * The @wakeshift/sdk stand-in. Only the unregistered watch_messages tool reaches
 * the SDK, so the module graph needs nothing more than a loadable shape.
 */

type Event = {
  name: string;
  emit: (args: unknown, payload: unknown, options?: unknown) => Promise<unknown>;
};

export class Wakeshift {
  defineEvent(name: string, _options?: unknown): Event {
    return {
      name,
      emit: async () => undefined,
    };
  }

  currentCall(): { subscribe: (event: unknown, args: unknown, options?: unknown) => Promise<unknown> } {
    return {
      subscribe: async () => undefined,
    };
  }
}

export function encodeArgValue(value: string): string {
  return value;
}
