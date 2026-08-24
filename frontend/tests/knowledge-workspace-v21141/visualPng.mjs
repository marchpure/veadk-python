import { inflateSync } from "node:zlib";

const PNG_SIGNATURE = Buffer.from("\x89PNG\r\n\x1a\n", "binary");

function paeth(left, above, upperLeft) {
  const prediction = left + above - upperLeft;
  const leftDistance = Math.abs(prediction - left);
  const aboveDistance = Math.abs(prediction - above);
  const upperLeftDistance = Math.abs(prediction - upperLeft);
  if (leftDistance <= aboveDistance && leftDistance <= upperLeftDistance) {
    return left;
  }
  return aboveDistance <= upperLeftDistance ? above : upperLeft;
}

function crc32(content) {
  let crc = 0xffffffff;
  for (const byte of content) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export function decodePng(content) {
  if (!content.subarray(0, 8).equals(PNG_SIGNATURE)) {
    throw new Error("screenshot evidence is not a PNG");
  }
  let offset = 8;
  let width;
  let height;
  let colorType;
  let bitDepth;
  let interlace;
  let sawIend = false;
  const compressed = [];
  while (offset < content.length) {
    const length = content.readUInt32BE(offset);
    const type = content.toString("ascii", offset + 4, offset + 8);
    const data = content.subarray(offset + 8, offset + 8 + length);
    if (offset + 12 + length > content.length) {
      throw new Error("truncated PNG evidence");
    }
    const expectedCrc = content.readUInt32BE(offset + 8 + length);
    const actualCrc = crc32(content.subarray(offset + 4, offset + 8 + length));
    if (actualCrc !== expectedCrc) {
      throw new Error(`PNG evidence has an invalid ${type} checksum`);
    }
    if (type === "IHDR") {
      width = data.readUInt32BE(0);
      height = data.readUInt32BE(4);
      bitDepth = data[8];
      colorType = data[9];
      interlace = data[12];
    } else if (type === "IDAT") {
      compressed.push(data);
    } else if (type === "IEND") {
      if (length !== 0 || offset + 12 !== content.length) {
        throw new Error("PNG evidence has trailing data after IEND");
      }
      sawIend = true;
      break;
    }
    offset += 12 + length;
  }
  if (
    !width ||
    !height ||
    bitDepth !== 8 ||
    ![2, 6].includes(colorType) ||
    interlace !== 0 ||
    compressed.length === 0 ||
    !sawIend
  ) {
    throw new Error("PNG evidence must be non-interlaced 8-bit RGB or RGBA");
  }
  const channels = colorType === 2 ? 3 : 4;
  const rowBytes = width * channels;
  const inflated = inflateSync(Buffer.concat(compressed));
  if (inflated.length !== height * (rowBytes + 1)) {
    throw new Error("PNG evidence has an invalid decoded size");
  }
  const decoded = Buffer.alloc(width * height * channels);
  let sourceOffset = 0;
  for (let y = 0; y < height; y += 1) {
    const filter = inflated[sourceOffset];
    sourceOffset += 1;
    if (filter > 4) throw new Error(`unsupported PNG filter: ${filter}`);
    const rowOffset = y * rowBytes;
    for (let x = 0; x < rowBytes; x += 1) {
      const raw = inflated[sourceOffset + x];
      const left = x >= channels ? decoded[rowOffset + x - channels] : 0;
      const above = y > 0 ? decoded[rowOffset + x - rowBytes] : 0;
      const upperLeft =
        y > 0 && x >= channels
          ? decoded[rowOffset + x - rowBytes - channels]
          : 0;
      let reconstructed = raw;
      if (filter === 1) reconstructed += left;
      if (filter === 2) reconstructed += above;
      if (filter === 3) reconstructed += Math.floor((left + above) / 2);
      if (filter === 4) reconstructed += paeth(left, above, upperLeft);
      decoded[rowOffset + x] = reconstructed & 0xff;
    }
    sourceOffset += rowBytes;
  }
  const rgba = Buffer.alloc(width * height * 4);
  for (let pixel = 0; pixel < width * height; pixel += 1) {
    rgba[pixel * 4] = decoded[pixel * channels];
    rgba[pixel * 4 + 1] = decoded[pixel * channels + 1];
    rgba[pixel * 4 + 2] = decoded[pixel * channels + 2];
    rgba[pixel * 4 + 3] =
      channels === 4 ? decoded[pixel * channels + 3] : 255;
  }
  return { width, height, rgba };
}

function isMasked(x, y, masks) {
  return masks.some(({ rectangle }) => {
    if (!Array.isArray(rectangle) || rectangle.length !== 4) return false;
    const [left, top, width, height] = rectangle;
    return x >= left && x < left + width && y >= top && y < top + height;
  });
}

export function comparePng(reference, candidate, masks, expectedDimensions) {
  const left = decodePng(reference);
  const right = decodePng(candidate);
  if (
    expectedDimensions &&
    (left.width !== expectedDimensions.width ||
      left.height !== expectedDimensions.height ||
      right.width !== expectedDimensions.width ||
      right.height !== expectedDimensions.height)
  ) {
    throw new Error("screenshot dimensions do not match viewport");
  }
  if (left.width !== right.width || left.height !== right.height) {
    return { dimensionsEqual: false, mismatchRatio: 1 };
  }
  let compared = 0;
  let mismatched = 0;
  for (let y = 0; y < left.height; y += 1) {
    for (let x = 0; x < left.width; x += 1) {
      if (isMasked(x, y, masks)) continue;
      compared += 1;
      const offset = (y * left.width + x) * 4;
      if (
        left.rgba[offset] !== right.rgba[offset] ||
        left.rgba[offset + 1] !== right.rgba[offset + 1] ||
        left.rgba[offset + 2] !== right.rgba[offset + 2] ||
        left.rgba[offset + 3] !== right.rgba[offset + 3]
      ) {
        mismatched += 1;
      }
    }
  }
  if (compared === 0) {
    throw new Error("visual masks exclude every screenshot pixel");
  }
  return {
    dimensionsEqual: true,
    mismatchRatio: mismatched / compared,
  };
}
