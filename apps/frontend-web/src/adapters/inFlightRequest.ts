export function createInFlightRequest<T>(load: () => Promise<T>): () => Promise<T> {
  let inFlight: Promise<T> | null = null;

  return () => {
    if (inFlight) return inFlight;

    const request = load().finally(() => {
      if (inFlight === request) {
        inFlight = null;
      }
    });
    inFlight = request;
    return request;
  };
}
