import fs from 'node:fs/promises';
import path from 'node:path';
import { FileBlob, PresentationFile } from '@oai/artifact-tool';
const root=path.resolve('.');
const file=path.join(root,'deliverables','Railway_Platforming_AI_Project_Presentation.pptx');
const output=path.join(root,'.artifact_build','final-deck-render');
await fs.mkdir(output,{recursive:true});
const p=await PresentationFile.importPptx(await FileBlob.load(file));
const inspect=await p.inspect({kind:'slide,notes,chart,table',maxChars:30000});
await fs.writeFile(path.join(output,'inspect.ndjson'),inspect.ndjson,'utf8');
for(let i=0;i<p.slides.items.length;i++){
 const blob=await p.export({slide:p.slides.items[i],format:'png',scale:1});
 await fs.writeFile(path.join(output,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify({slides:p.slides.items.length,rendered:(await fs.readdir(output)).filter(x=>x.endsWith('.png')).length,inspect:path.join(output,'inspect.ndjson')}));
