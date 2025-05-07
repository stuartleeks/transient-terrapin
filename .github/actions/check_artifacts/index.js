import * as core from '@actions/core';
import * as github from '@actions/github';
import fs from 'fs';
import path from 'path';
import yaml from 'yaml';
import { fileURLToPath } from 'url';
import { DefaultArtifactClient, ArtifactNotFoundError } from '@actions/artifact';
import { restoreCache } from '@actions/cache'

import {DefaultAzureCredential} from '@azure/identity';
import { BlobServiceClient, StorageSharedKeyCredential } from "@azure/storage-blob";


const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const artifactsFile = core.getInput('artifacts-file');
if (!artifactsFile) {
  core.setFailed('artifacts-file input is required');
}
console.log(`Artifacts file: ${artifactsFile}`);

const storageAccountName = core.getInput('storage-account', {required: true});
const containerName = core.getInput('container', {required: true});

//
// This action reads a YAML file containing a list of artifacts.
// Each artifact has a filter name and a suffix.
// The filter indicates the repo subtree content that is hashed to identify changes
// The suffix indicates the artifact purpose and allows multiple artifacts for the same subtree
//
// The hashes are loaded from the .hashes directory and need to be generated before the action runs
//
// The action checks if the artifacts exist in the GitHub repository and sets outputs for each artifact
// The outputs are:
// - artifact_fingerprint_<filter_name>: the fingerprint of the artifact. This should be used to fetch/store the artifact
// - artifact_exists_<filter_name>: true if the artifact exists, false otherwise
//

// NOTE: The term artifact is used here but generally refers to cache items
//       since GH artifacts are scoped to a workflow run.
//       The list of artifact keys and hashs _is_ stored as a workflow artifact

const azCredential = new  DefaultAzureCredential();
const blobClient = new BlobServiceClient(
  `https://${storageAccountName}.blob.core.windows.net`,
  azCredential
);
const containerClient = blobClient.getContainerClient(containerName)


function getHashes() {
  const hashes = {};
  // List files in .hashes directory and load each file
  const dirPath = path.join(__dirname, '../../../.hashes');
  const files = fs.readdirSync(dirPath);
  files.forEach(file => {
    const filePath = path.join(dirPath, file);
    const fileContent = fs.readFileSync(filePath, 'utf8');
    const filterName = path.basename(filePath, ".hash");
    hashes[filterName] = fileContent;
  });
  return hashes;
}


async function testArtifactExists(artifactKey) {
  const blobName = `${artifactKey}/artifacts.zip`;
  const exists = await containerClient.getBlobClient(blobName).exists()
  console.log(`Blob ${blobName} exists: ${exists}`);
  return exists;
}

const hashes = getHashes();
console.log("==== hashes ====");
console.log(hashes);


// Load the artifacts file and parse the YAML
const artifactsFilePath = path.join(__dirname, '../../../', artifactsFile);
const artifactsFileContent = fs.readFileSync(artifactsFilePath, 'utf8');
const artifacts = yaml.parse(artifactsFileContent);



console.log("==== artifacts ====");
const artifactFingerprintDictionary = {};
const artifactExistsDictionary = {};
// const artifactPrefix = github.context.repo.owner + "_" + github.context.repo.repo;
const artifactPrefix = github.context.repo.owner + "/" + github.context.repo.repo;
for (const artifact of artifacts) {
  const { filter_name, suffix } = artifact;
  const artifactName = `${filter_name}_${suffix}`;
  // const fingerprint = `${artifactPrefix}_${artifactName}_${hashes[filter_name]}`;
  const fingerprint = `${artifactPrefix}/${artifactName}_${hashes[filter_name]}`;
  const artifactExists = await testArtifactExists(fingerprint);
  console.log(`Artifact fingerprint: ${fingerprint} - exists: ${artifactExists}`);
  // Set outputs for the fingerprint for each artifact
  // and whether the artifact exists
  console.log(`Set output artifact_fingerprint_${artifactName}: ${fingerprint}`);
  console.log(`Set output artifact_exists_${artifactName}: ${artifactExists}`);
  core.setOutput(`artifact_fingerprint_${artifactName}`, fingerprint);
  core.setOutput(`artifact_exists_${artifactName}`, artifactExists);

  
  artifactFingerprintDictionary[artifactName] = fingerprint;
  artifactExistsDictionary[artifactName] = artifactExists;
}

console.log("==== outputs ====");
const artifactFingerprintJson = JSON.stringify(artifactFingerprintDictionary);
const artifactExistsJson = JSON.stringify(artifactExistsDictionary);
console.log("artifact_fingerprint", artifactFingerprintJson);
console.log("artifact_exists", artifactExistsJson);

core.setOutput("fingerprint", artifactFingerprintJson);
core.setOutput("exists", artifactExistsJson);
core.setOutput("test", JSON.stringify({ a: 123, b: 234 }));

const stepSummaryFile = process.env.GITHUB_STEP_SUMMARY;
if (stepSummaryFile) {
  fs.appendFileSync(stepSummaryFile, `\n\n## Artifacts\n\n`);
  fs.appendFileSync(stepSummaryFile, `|Artifact| Fingerprint| Exists|\n`);
  fs.appendFileSync(stepSummaryFile, `|---|---|---|\n`);
}


// Write JSON file with the outputs to save as an artifact
// Also write to the step summary
const artifactOutputDirectory = path.join(__dirname, '../../../');
const artifactOutputFile = path.join(artifactOutputDirectory, '.artifacts.json');
const result = {};
for (const artifact of artifacts) {
  const { filter_name, suffix } = artifact;
  const artifactName = `${filter_name}_${suffix}`;
  const fingerprint = artifactFingerprintDictionary[artifactName];
  const exists = artifactExistsDictionary[artifactName];
  result[artifactName] = {
    fingerprint,
    exists,
  };
  fs.appendFileSync(stepSummaryFile, `|${artifactName}| ${fingerprint}| ${exists}|\n`);
}
fs.writeFileSync(artifactOutputFile, JSON.stringify(result, null, 2), 'utf8');



const artifactClient = new DefaultArtifactClient()
const artifactResultKey = `artifact_summary`;
core.setOutput("artifact_result_key", artifactResultKey);
artifactClient.uploadArtifact(artifactResultKey, [artifactOutputFile], artifactOutputDirectory, { retentionDays: 1 });


