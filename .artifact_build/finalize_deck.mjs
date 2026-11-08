import path from 'node:path';
import fs from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const workspaceDir = path.resolve('.');
const SKILL_DIR = 'C:/Users/Md Arif/.codex/plugins/cache/openai-primary-runtime/presentations/26.1105.12137/skills/presentations';
const candidatePath = path.join(workspaceDir,'.artifact_build','Railway_Platforming_AI_Project_Presentation_draft.pptx');
const finalPath = path.join(workspaceDir,'deliverables','Railway_Platforming_AI_Project_Presentation.pptx');
const RUNTIME_PYTHON = 'C:/Users/Md Arif/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe';
process.env.RUNTIME_NODE_MODULES = 'C:/Users/Md Arif/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const { finalizePresentation } = await import(pathToFileURL(path.join(SKILL_DIR,'container_tools/artifact_tool_utils.mjs')).href);
const stagingDir = path.join(workspaceDir,'.artifact_build','finalizer');
await fs.mkdir(stagingDir,{recursive:true});
const result = await finalizePresentation({
  explicitTotalSlideCount: 23,
  requiredNativeTableOwnerSlides: [4,9,10,17,20],
  requiredNativeChartOwnerSlides: [8,19],
  materializeLiteralChartWorkbooks: true,
  workspaceDir,
  candidatePath,
  finalPath,
  pythonExecutable: RUNTIME_PYTHON,
  integrityValidatorPath: path.join(SKILL_DIR,'container_tools/inspect_presentation_package_integrity.py'),
  layoutValidatorPath: path.join(SKILL_DIR,'container_tools/inspect_presentation_layout_geometry.py'),
  layoutArgs: ['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',
    ...[4,9,10,17,20].flatMap(n=>['--require-native-table-slide',String(n)])],
  fontPolicy: {basis:'design',families:['Arial']},
  verifyArtifactToolImport: true,
  receiptPath: path.join(stagingDir,'presentation-validation.json'),
});
console.log(JSON.stringify(result,null,2));
