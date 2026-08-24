// Google's encoded polyline algorithm. A dependency for 25 lines is not worth it.

/**
 * Decodes an encoded polyline to GeoJSON coordinate order.
 *
 * Google emits latitude first; GeoJSON and MapLibre want [lng, lat], so the pair is swapped on the
 * way out rather than at every call site.
 */
export function decodePolyline(encoded: string): [number, number][] {
  const out: [number, number][] = [];
  let index = 0;
  let lat = 0;
  let lng = 0;

  while (index < encoded.length) {
    // Each value is a chain of 5-bit groups, low group first, with bit 6 set on all but the last.
    for (let i = 0; i < 2; i++) {
      let result = 0;
      let shift = 0;
      let byte: number;
      do {
        byte = encoded.charCodeAt(index++) - 63;
        result |= (byte & 0x1f) << shift;
        shift += 5;
      } while (byte >= 0x20 && index < encoded.length);
      // The sign lives in bit 0 of the assembled value, and the magnitude is a delta.
      const delta = result & 1 ? ~(result >> 1) : result >> 1;
      if (i === 0) lat += delta;
      else lng += delta;
    }
    out.push([lng / 1e5, lat / 1e5]);
  }
  return out;
}
