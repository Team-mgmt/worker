import {
  ListObjectsV2Command,
  PutObjectTaggingCommand,
  S3Client,
} from "@aws-sdk/client-s3";

const CONCURRENCY = 200;
const TAG_KEY = "lifecycle";
const TAG_VALUE = "outdated";

function parseArgs(argv) {
  const locationIndex = argv.indexOf("--location");
  if (locationIndex === -1 || !argv[locationIndex + 1]) {
    throw new Error(
      "Usage: tag-existing-assets.mjs --location BUCKET[/PREFIX]",
    );
  }
  return { location: argv[locationIndex + 1] };
}

function parseLocation(location) {
  const trimmed = location.replace(/\/+$/, "");
  const slash = trimmed.indexOf("/");
  if (slash === -1) return { bucket: trimmed, prefix: "" };
  return {
    bucket: trimmed.slice(0, slash),
    prefix: `${trimmed.slice(slash + 1)}/`,
  };
}

async function listAllKeys(client, bucket, prefix) {
  const keys = [];
  let token;
  do {
    const res = await client.send(
      new ListObjectsV2Command({
        Bucket: bucket,
        Prefix: prefix || undefined,
        ContinuationToken: token,
      }),
    );
    if (res.Contents) {
      for (const obj of res.Contents) {
        if (obj.Key) keys.push(obj.Key);
      }
    }
    token = res.NextContinuationToken;
  } while (token);
  return keys;
}

async function tagAll(client, bucket, keys) {
  const total = keys.length;
  let cursor = 0;
  let tagged = 0;

  async function worker() {
    while (cursor < total) {
      const i = cursor++;
      const key = keys[i];
      await client.send(
        new PutObjectTaggingCommand({
          Bucket: bucket,
          Key: key,
          Tagging: { TagSet: [{ Key: TAG_KEY, Value: TAG_VALUE }] },
        }),
      );
      tagged++;
      if (tagged % 1000 === 0) {
        console.log(`  Tagged ${tagged}/${total}`);
      }
    }
  }

  const workers = Array.from(
    { length: Math.min(CONCURRENCY, total) },
    worker,
  );
  await Promise.all(workers);
  return tagged;
}

async function main() {
  const { location } = parseArgs(process.argv.slice(2));
  const { bucket, prefix } = parseLocation(location);
  const display = prefix ? `s3://${bucket}/${prefix}` : `s3://${bucket}/`;

  const client = new S3Client({});

  console.log(`Listing objects in ${display}`);
  const keys = await listAllKeys(client, bucket, prefix);

  if (keys.length === 0) {
    console.log(`No existing objects to tag in ${display}`);
    return;
  }

  console.log(
    `Tagging ${keys.length} objects in ${display} as ${TAG_KEY}=${TAG_VALUE}`,
  );
  const start = Date.now();
  const tagged = await tagAll(client, bucket, keys);
  const elapsed = ((Date.now() - start) / 1000).toFixed(1);
  console.log(`Tagged ${tagged} objects in ${elapsed}s`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
