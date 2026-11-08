import fs from 'node:fs/promises';
import path from 'node:path';
import { Presentation, PresentationFile } from '@oai/artifact-tool';

const ROOT = path.resolve('.');
const BUILD = path.join(ROOT, '.artifact_build');
const FINAL = path.join(ROOT, 'deliverables', 'Railway_Platforming_AI_Project_Presentation.pptx');
const DRAFT = path.join(BUILD, 'Railway_Platforming_AI_Project_Presentation_draft.pptx');
const evalData = JSON.parse(await fs.readFile(path.join(ROOT, 'output/evaluation.json'), 'utf8'));
const normal = JSON.parse(await fs.readFile(path.join(ROOT, 'output/platform_twin_evaluation.json'), 'utf8'));
const busy = JSON.parse(await fs.readFile(path.join(ROOT, 'output/ndls_busy_scenario/platform_twin_evaluation.json'), 'utf8'));
const pool = evalData.all_station_model;
const ndls = evalData.station_specific;
const comparisons = evalData.model_comparison.filter(x => x.kind === 'xgboost_metaheuristic');

const C = { navy:'#142B45', teal:'#168A91', cyan:'#44B9C8', ink:'#203040', muted:'#607080', paper:'#F5F7FA', white:'#FFFFFF', line:'#D8E0E8', pale:'#E7F3F4', red:'#B94B4B', gold:'#C79536', green:'#3A805D' };
const pres = Presentation.create({slideSize:{width:1280,height:720}});

function rect(slide,x,y,w,h,fill,stroke='none',sw=0){
  return slide.shapes.add({geometry:'rect',position:{left:x,top:y,width:w,height:h},fill,
    line:{style:'solid',fill:stroke,width:sw}});
}
function txt(slide,text,x,y,w,h,size=22,color=C.ink,bold=false,opts={}){
  const s=slide.shapes.add({geometry:'textbox',name:opts.name,position:{left:x,top:y,width:w,height:h},fill:'none',line:{style:'solid',fill:'none',width:0}});
  s.text=text;
  s.text.style={fontFamily:'Arial',fontSize:size,color,bold,verticalAlignment:opts.valign||'middle',alignment:opts.align||'left',wrap:true};
  return s;
}
function note(slide, text){ slide.speakerNotes.text=text; }
function frame(section,title,n,notes=''){
  const s=pres.slides.add(); s.background.fill=C.paper;
  rect(s,0,0,1280,12,C.teal);
  txt(s,section.toUpperCase(),64,34,500,24,13,C.teal,true);
  txt(s,title,64,66,1150,56,32,C.navy,true);
  rect(s,64,130,1152,2,C.line);
  txt(s,'Railway delay prediction and platform scheduling',64,678,900,18,12,C.muted,false);
  txt(s,String(n).padStart(2,'0'),1172,674,40,22,13,C.muted,true,{align:'right'});
  if(notes) note(s,notes);
  return s;
}
function paragraph(slide, text, x=74,y=158,w=1120,h=92,size=21,color=C.ink){ txt(slide,text,x,y,w,h,size,color,false,{valign:'top'}); }
function labelValue(slide,label,value,x,y,w=330){
  rect(slide,x,y,w,112,C.white,C.line,1);
  txt(slide,label.toUpperCase(),x+18,y+14,w-36,22,13,C.teal,true);
  txt(slide,value,x+18,y+42,w-36,48,29,C.navy,true);
}
function bulletRows(slide, rows, x=82,y=170,width=1100,gap=68,size=20){
  rows.forEach((t,i)=>{ rect(slide,x,y+i*gap+7,9,9,C.teal); txt(slide,t,x+24,y+i*gap,width-24,gap-8,size,C.ink,false,{valign:'top'}); });
}
function table(slide, rows, x,y,w,h, widths){
  const t=slide.tables.add({rows:rows.length,columns:rows[0].length,left:x,top:y,width:w,height:h,values:rows,columnWidths:widths});
  for(let r=0;r<rows.length;r++) for(let c=0;c<rows[0].length;c++){
    const cell=t.getCell(r,c); cell.fill=r===0?C.navy:(r%2?C.white:'#EAF0F5');
    cell.text.style={fontFamily:'Arial',fontSize:r===0?17:16,color:r===0?C.white:C.ink,bold:r===0};
  }
  return t;
}
function flowBox(slide,title,body,x,y,w,h,fill=C.white){
  rect(slide,x,y,w,h,fill,C.line,1); txt(slide,title,x+14,y+14,w-28,28,17,C.teal,true); txt(slide,body,x+14,y+48,w-28,h-58,16,C.ink,false,{valign:'top'});
}

// 1 Cover
{
 const s=pres.slides.add(); s.background.fill=C.navy;
 rect(s,0,0,18,720,C.teal); rect(s,72,96,104,6,C.cyan);
 txt(s,'RAILWAY AI MINOR PROJECT',74,72,700,26,15,C.cyan,true);
 txt(s,'Delay Prediction and\nPlatform Scheduling',72,145,930,150,48,C.white,true,{valign:'top'});
 txt(s,'XGBoost-PSO prediction with a configurable NDLS platform twin',76,322,900,58,23,'#D5E1EB',false);
 txt(s,'Interactive dashboard  |  SimPy event simulation  |  10,000-run stress test',76,406,1000,36,18,C.cyan,false);
 rect(s,76,510,580,1,'#476178');
 txt(s,'Minor Project Report Presentation',76,536,800,30,18,C.white,true);
 txt(s,'8 November 2026',76,576,500,25,15,'#C0CED9',false);
 note(s,'Project summary based on the current repository artifacts. Prediction metrics are historical holdout results. Platform results are synthetic scenario outputs, not observed NDLS operations.');
}
// 2 Index slide
{
 const s=frame('Navigation','Presentation index',2,'The index maps the deck sections. Research and product facts are cited in the relevant slide notes.');
 const items=[
  ['01','Project framing','Slides 3–4'],['02','Review papers and data','Slides 5–6'],
  ['03','Prediction model and results','Slides 7–11'],['04','Dashboard and architecture','Slides 12–13'],
  ['05','Platform scheduling and safety','Slides 14–15'],['06','Digital Twin and scenarios','Slides 16–17'],
  ['07','Stress test and target scorecard','Slides 18–20'],['08','Limits, conclusion, references','Slides 21–23'],
 ];
 items.forEach((it,i)=>{const col=i%2,row=Math.floor(i/2),x=76+col*565,y=164+row*116; rect(s,x,y,532,90,C.white,C.line,1);txt(s,it[0],x+18,y+20,50,42,27,C.teal,true);txt(s,it[1],x+82,y+15,290,31,20,C.navy,true);txt(s,it[2],x+82,y+52,380,24,16,C.muted,false);});
}
// 3 Project overview
{
 const s=frame('Project framing','One project, two evidence layers',3,'Historical prediction metrics come from the held-out Indian train-history sample. Scheduler metrics come from configurable synthetic scenarios. Dataset: https://huggingface.co/datasets/yadavsaurabh/indian-railways-runs');
 labelValue(s,'Prediction','Next-stop delay',76,174,345);labelValue(s,'Model selection','XGBoost-PSO',467,174,345);labelValue(s,'System extension','Platform twin',858,174,345);
 paragraph(s,'The existing prediction pipeline remains intact. New components consume its delay estimates to demonstrate station scheduling under explicit, editable assumptions.',82,330,1090,76,22);
 bulletRows(s,['Historical test scores are measured against reported delay labels.','Platform timetables, lengths, dwell and priorities are generated demo inputs.','The app is an offline educational decision-support prototype, not railway control.'],84,426,1080,58,19);
}
// 4 Scope and objectives
{
 const s=frame('Project framing','Synopsis scope implemented',4,'Scope mapped from the user-provided minor-project synopsis.');
 table(s,[['Component','Implementation','Evidence'],['Delay prediction','XGBoost-PSO, four optimizer comparison, 90% intervals','Evaluation JSON + test CSV'],['Explainability','Native TreeSHAP grouped to 13 original features','Dashboard local explanations'],['Platform allocation','Weighted intervals, priority, FCFS wait safeguard','Schedule CSV + metrics JSON'],['Safety rules','Train length and 5-minute clearance checks','Violation counters'],['Digital Twin','SimPy single-capacity platform resources','Wait, use, throughput metrics'],['Stress testing','10,000 seeded perturbations','Wait percentiles + conflict risk']],72,160,1136,440,[245,520,371]);
}
// 5 Literature review
{
 const s=frame('Related research','Three papers guide the design',5,'Primary sources: Gao et al. (2024), https://doi.org/10.1049/itr2.12461 ; Tiong et al. (2023), https://doi.org/10.1016/j.trc.2023.104027 ; Spanninger et al. (2022), https://doi.org/10.1016/j.jrtpm.2022.100312');
 flowBox(s,'Tiong, Ma & Palmqvist (2023)','Reviews data-driven delay prediction; highlights data quality, validity, explainability and evaluation.',78,170,350,220);
 flowBox(s,'Spanninger et al. (2022)','Classifies data-driven and event-driven approaches, prediction types, inputs and horizons.',465,170,350,220);
 flowBox(s,'Gao, Chen & Xu (2024)','XGBoost with GA, PSO, WOA and GWO; dispatch-command features and SHAP.',852,170,350,220);
 paragraph(s,'Project adaptation: compare the same four tuners and add SHAP, but do not claim to reproduce Gao’s data or performance.',90,436,1090,72,21);
 txt(s,'1.9M records in Gao et al. are not this project’s dataset.',90,542,1090,36,20,C.teal,true);
}
// 6 Dataset
{
 const s=frame('Data','A route-biased extract, not a national benchmark',6,'Dataset card: https://huggingface.co/datasets/yadavsaurabh/indian-railways-runs . Current model run uses seven cached train histories. The dataset card declares GPL-3.0.');
 labelValue(s,'Raw stop rows','281,252',78,175,340);labelValue(s,'Engineered examples','164,297',470,175,340);labelValue(s,'Final pooled test','42,997',862,175,340);
 paragraph(s,'Target: reported arrival delay at the immediate next reported station. Examples are paired within train and journey date.',88,340,1090,70,21);
 bulletRows(s,['Dates span 2020-01-01 to 2026-09-01 in this extract.','Current and next station, run time, distance, dwell, route sequence and current delay form the inputs.','Actual future timestamps, future delay and platform labels are excluded from model features.'],90,435,1080,55,19);
}
// 7 Prediction workflow
{
 const s=frame('Prediction','Chronological evaluation prevents date leakage',7,'Counts and split design from output/evaluation.json.');
 const stages=[['Train','79,001'],['Validation','20,648'],['Calibration','21,651'],['Test','42,997']];
 stages.forEach((it,i)=>{const x=78+i*284;flowBox(s,it[0],`${it[1]} examples`,x,190,244,126,i===3?'#FFF7E6':C.white);if(i<3)txt(s,'→',x+250,225,35,35,27,C.teal,true,{align:'center'});});
 paragraph(s,'Validation selects the optimizer. Calibration sets the 90th-percentile residual radius. The later-date test is held back until final scoring.',90,368,1080,64,21);
 bulletRows(s,['13 features: 3 categorical and 10 numeric.','The model predicts delay at the next stop from current-stop information.','The temporal split still includes the same route and train patterns across dates.'],92,462,1070,54,18);
}
// 8 Optimizer comparison
{
 const s=frame('Prediction','PSO has the lowest validation RMSE',8,'Optimizer validation scores from output/evaluation.json. Search: population 6, two generations, bounded training sample 6,000 and validation sample 2,500. Adapted from Gao et al., not a reproduction. Source: https://doi.org/10.1049/itr2.12461');
 const sorted=[...comparisons].sort((a,b)=>a.rmse_min-b.rmse_min);
 s.charts.add('bar',{position:{left:120,top:166,width:1030,height:390},categories:sorted.map(x=>x.algorithm.replace('XGBoost-','')),series:[{name:'Validation RMSE (min)',values:sorted.map(x=>Number(x.rmse_min.toFixed(3))),fill:C.teal}],hasLegend:false,
   dataLabels:{showValue:true,position:'outEnd'},xAxis:{title:'Optimizer'},yAxis:{title:'Validation RMSE (minutes)',min:0,majorGridlines:{style:'solid',fill:C.line,width:1}}});
 txt(s,'Selected by validation RMSE; the final test dates were not used for selection.',100,590,1060,32,18,C.muted,false);
}
// 9 Pooled and NDLS final metrics
{
 const s=frame('Prediction','Final holdout results',9,'Metrics from the untouched chronological test partition.');
 table(s,[['Model','N','MAE (min)','RMSE (min)','R²','90% coverage'],['Pooled',pool.n.toLocaleString(),pool.mae_min.toFixed(2),pool.rmse_min.toFixed(2),pool.r2.toFixed(3),`${(100*pool.interval_coverage_90_nominal).toFixed(1)}%`],['NDLS only',String(ndls.n),ndls.mae_min.toFixed(2),ndls.rmse_min.toFixed(2),ndls.r2.toFixed(3),`${(100*ndls.interval_coverage_90_nominal).toFixed(1)}%`]],90,190,1100,210,[240,140,180,180,140,220]);
 txt(s,'Selected model: XGBoost-PSO',94,455,1050,45,28,C.navy,true);
 txt(s,'The synopsis target of MAE < 4.5 min is not met. NDLS has only 62 test examples.',94,512,1080,58,21,C.red,true);
}
// 10 Station scores
{
 const s=frame('Prediction','Pooled scores vary by target station',10,'Station-level final-test scores are from the pooled model; station groups with fewer than 50 rows are omitted.');
 const examples=[['AGC','346','6.04','6.62','0.981'],['GWL','281','5.14','7.08','0.985'],['NDLS','62','9.77','12.68','0.981']];
 table(s,[['Target station','Test rows','MAE (min)','RMSE (min)','R²'],...examples],140,190,1000,240,[270,160,190,190,190]);
 paragraph(s,'NDLS row above is the separate NDLS-only temporal model. AGC and GWL are pooled-model station slices; these are not the same evaluation.',112,486,1050,70,20);
 txt(s,'A high R² can coexist with meaningful absolute error.',112,575,1050,34,19,C.teal,true);
}
// 11 Uncertainty and explanations
{
 const s=frame('Prediction','Intervals and TreeSHAP make estimates auditable',11,'TreeSHAP uses XGBoost native pred_contribs on the fitted pipeline. Five-row NDLS check maximum additive reconstruction error was 0.000042 min. Literature: Lundberg & Lee (2017), NeurIPS 30; Gao et al. (2024).');
 labelValue(s,'Pooled 90% radius','13.08 min',80,180,350);labelValue(s,'Pooled coverage','89.1%',465,180,350);labelValue(s,'NDLS coverage','90.3%',850,180,350);
 paragraph(s,'A symmetric residual interval is calibrated on held-out calibration dates. For each uploaded prediction, TreeSHAP shows which inputs raise or lower the estimate relative to the model baseline.',92,344,1080,72,20);
 bulletRows(s,['Positive contribution: pushes predicted delay higher.','Negative contribution: pushes predicted delay lower.','SHAP is an explanation of the fitted model, not causal evidence.'],96,450,1060,55,19);
}
// 12 Dashboard
{
 const s=frame('Interactive dashboard','Prediction tables stay; readable summaries are added',12,'Dashboard implementation in src/dashboard.py. Streamlit documentation: https://docs.streamlit.io/');
 const tabs=['Project steps','Final results','Algorithm comparison','Station results','Prediction audit','Make predictions','Data and metrics','Platform twin'];
 tabs.forEach((t,i)=>{const x=78+(i%4)*280,y=184+Math.floor(i/4)*150;rect(s,x,y,250,102,C.white,C.line,1);txt(s,String(i+1).padStart(2,'0'),x+16,y+16,45,27,15,C.teal,true);txt(s,t,x+16,y+50,220,36,18,C.navy,true);});
 paragraph(s,'The prediction view keeps the detailed CSV table and adds summary metrics, a point-and-interval chart, and TreeSHAP contributions. The platform view adds per-platform utilization, allocation explanations and CSV export.',88,510,1080,90,19);
}
// 13 System architecture
{
 const s=frame('System design','Prediction outputs feed a separate simulation layer',13,'Architecture reflects the current codebase; historical delay labels are used only in model evaluation.');
 flowBox(s,'Historical run data','7 cached files\n281,252 stop rows',75,220,220,150);
 flowBox(s,'Feature + model','13 inputs\nXGBoost-PSO',350,220,220,150);
 flowBox(s,'Prediction CSV','Delay point\n90% range',625,220,220,150);
 flowBox(s,'Scenario builder','Synthetic slot, dwell, length, priority',900,220,285,150);
 [305,580,855].forEach(x=>txt(s,'→',x,272,35,40,30,C.teal,true,{align:'center'}));
 flowBox(s,'Platform scheduler + SimPy','FCFS comparison, safety checks, Gantt and 10,000-run stress test',350,455,500,120,C.pale);
 txt(s,'Offline educational use only. No live feed, signal logic or dispatch authority.',878,486,300,62,17,C.red,true);
}
// 14 Scheduler
{
 const s=frame('Platform scheduling','Weighted intervals assign feasible reservations',14,'Algorithm implementation: src/railway_delay/platforming.py. It creates a candidate priority-weighted interval plan and uses a minimum-wait FCFS safeguard when that candidate increases total wait.');
 const steps=[['1','Estimate arrival','Scheduled slot + predicted delay'],['2','Check length','Train length ≤ platform length'],['3','Select intervals','Avoid overlap; retain 5 min clearance'],['4','Resolve conflicts','Priority order; move not-yet-started reservations'],['5','Compare wait','Choose lower-wait feasible plan']];
 steps.forEach((it,i)=>{const y=159+i*88;rect(s,82,y,58,58,C.teal);txt(s,it[0],82,y+2,58,52,24,C.white,true,{align:'center'});txt(s,it[1],170,y,260,29,20,C.navy,true);txt(s,it[2],430,y,700,38,18,C.ink,false);if(i<steps.length-1)rect(s,109,y+60,2,24,C.line);});
}
// 15 Safety checks
{
 const s=frame('Platform safety checks','Two hard constraints are checked in every schedule',15,'These are simplified software checks, not an operational railway safety case.');
 labelValue(s,'Length constraint','Train ≤ platform length',85,190,500);labelValue(s,'Release clearance','At least 5 min',690,190,500);
 paragraph(s,'Each platform is a single-capacity resource. An overlength train is left unassigned. A service cannot start until the prior simulated dwell and clearance have ended.',100,380,1060,70,21);
 bulletRows(s,['Default demo: six 700 m platforms; configurable from 4–8 platforms.','Configured scenario inputs are synthetic because verified station infrastructure is not available in the project extract.','Zero modeled violations do not certify real signal, route, braking or interlocking safety.'],102,474,1065,55,18);
}
// 16 SimPy + FCFS
{
 const s=frame('Digital Twin','SimPy models platform occupancy as limited resources',16,'SimPy is a process-based discrete-event simulation framework with limited-capacity shared resources: https://simpy.readthedocs.io/en/stable/simpy_intro/shared_resources.html');
 flowBox(s,'Arrival event','Wait until requested service time',84,205,250,145);
 flowBox(s,'Resource request','Queue for assigned platform',376,205,250,145);
 flowBox(s,'Dwell event','Occupy platform for scenario dwell',668,205,250,145);
 flowBox(s,'Release event','Apply 5-minute clearance',960,205,240,145);
 [342,634,926].forEach(x=>txt(s,'→',x,254,30,40,28,C.teal,true,{align:'center'}));
 paragraph(s,'FCFS assigns each movement to the compatible platform available earliest. Both policies use the same arrival stream, lengths, dwell and clearance. The simulator reports wait, utilization, throughput and service count.',100,425,1060,86,20);
}
// 17 Scenario comparison
{
 const s=frame('Simulation results','The busy case reaches FCFS after a wait safeguard',17,'Synthetic scenarios generated with fixed seeds. The 36-movement case uses 6 platforms, moderate demand, seed 42. The 60-movement case uses 4 platforms, busy demand, seed 7.');
 table(s,[['Scenario','Movements / platforms','FCFS wait (min)','Selected wait (min)','Change'],['Moderate',`36 / 6`,normal.fcfs.total_wait_min.toFixed(1),normal.optimized.total_wait_min.toFixed(1),`${normal.wait_reduction_pct_vs_fcfs.toFixed(1)}%`],['Busy',`60 / 4`,busy.fcfs.total_wait_min.toFixed(1),busy.optimized.total_wait_min.toFixed(1),`${busy.wait_reduction_pct_vs_fcfs.toFixed(1)}%`]],88,200,1100,230,[230,250,220,220,180]);
 paragraph(s,'Moderate: no queueing. Busy: 906.02 wait-minutes under both policies after the FCFS safeguard. Neither run supports the synopsis target of 30% wait reduction.',104,493,1065,72,21);
}
// 18 Stress method
{
 const s=frame('Stress testing','10,000 perturbations test sensitivity to timing and capacity',18,'Randomized ranges are explicit scenario assumptions, not empirical railway failure distributions.');
 flowBox(s,'Arrival shock','Normal(0, 5 min)',82,210,250,145);
 flowBox(s,'Dwell change','Uniform(0.85, 1.35) × dwell',376,210,250,145);
 flowBox(s,'Platform outage','2% chance if >4 platforms',670,210,250,145);
 flowBox(s,'Metrics','Wait percentiles, risk, capacity',964,210,240,145);
 [340,634,928].forEach(x=>txt(s,'→',x,257,30,38,28,C.teal,true,{align:'center'}));
 paragraph(s,'The fast replay uses single-capacity platform queues and tracks static conflicts before queue recovery separately from resource collisions after recovery.',103,432,1065,82,20);
}
// 19 Stress results chart
{
 const s=frame('Stress results','Default case has low wait; conflict risk appears in 10.2% of runs',19,'10,000 runs, seed 2068. Static conflict risk means nominal platform reservations overlap after perturbation. Zero post-queue resource collisions are guaranteed by the exclusive resource model and are not a safety certification.');
 const st=normal.stress_test;
 s.charts.add('bar',{position:{left:150,top:170,width:990,height:360},categories:['Mean','P95','P99','Maximum'],series:[{name:'Total wait (min)',values:[st.total_wait_min.mean,st.total_wait_min.p95,st.total_wait_min.p99,st.total_wait_min.max].map(v=>Number(v.toFixed(3))),fill:C.cyan}],hasLegend:false,dataLabels:{showValue:true,position:'outEnd'},xAxis:{title:'Stress summary'},yAxis:{title:'Total wait (minutes)',min:0,majorGridlines:{style:'solid',fill:C.line,width:1}}});
 txt(s,`${st.runs_with_static_platform_conflict_risk_before_queue_recovery.toLocaleString()} / 10,000 runs had a static conflict risk; 0 queue-resource collisions after recovery.`,112,567,1060,45,19,C.navy,true);
}
// 20 Goal scorecard
{
 const s=frame('Evaluation','Synopsis targets are reported as measured',20,'Targets copied from the user-provided synopsis. Measured results come from the current evaluation and synthetic scenario output.');
 table(s,[['Target','Measured result','Status'],['Prediction MAE < 4.5 min',`Pooled ${pool.mae_min.toFixed(2)}; NDLS ${ndls.mae_min.toFixed(2)}`,'Not met'],['Total wait reduction ≥30%',`Busy case ${busy.wait_reduction_pct_vs_fcfs.toFixed(1)}%`,'Not met'],['Near-zero modeled conflicts','0 length / clearance violations','Met within model rules'],['Secondary utilization +25%','No such gain observed','Not met'],['Recompute <50 ms','Scenario and hardware dependent','Not established']],85,180,1110,370,[370,480,260]);
}
// 21 Limits
{
 const s=frame('Interpretation','Synthetic station inputs limit operational claims',21,'The dataset card includes a platform field, but the project does not use it as a verified assignment or infrastructure source.');
 bulletRows(s,['Seven train histories; route-biased sample and shared services across date partitions.','NDLS temporal holdout has 62 examples; model performance at unseen services is not established.','Timetable, dwell, priority, train length and platform length are demo inputs.','No route locking, signal aspects, track conflicts, passenger access or dispatch authority.','Queue collision results are structural properties of the simplified resource model.'],95,170,1080,78,20);
}
// 22 Conclusion
{
 const s=frame('Conclusion','The requested workflow is implemented; target gains remain unproven',22,'Summary of implemented code and current measured outputs.');
 txt(s,'Prediction',90,180,230,30,17,C.teal,true);txt(s,'XGBoost-PSO retained; pooled MAE 6.44 min; NDLS MAE 9.77 min; TreeSHAP added.',90,218,1060,54,22,C.navy,true);
 txt(s,'Scheduling',90,322,230,30,17,C.teal,true);txt(s,'WIS + priority resolution, length and clearance checks, SimPy, FCFS and Gantt view.',90,360,1060,54,22,C.navy,true);
 txt(s,'Next step',90,464,230,30,17,C.teal,true);txt(s,'Replace demo station assumptions with verified operating data, then repeat external evaluation.',90,502,1060,54,22,C.navy,true);
}
// 23 References
{
 const s=frame('References','Selected references',23,'Full links are included in speaker notes on the relevant research and method slides.');
 const refs=[
  'Gao, T., Chen, J., & Xu, H. (2024). Data-driven train delay prediction incorporating dispatching commands: An XGBoost-metaheuristic framework. IET Intelligent Transport Systems, 18(10), 1777–1796. doi:10.1049/itr2.12461',
  'Tiong, K. Y., Ma, Z., & Palmqvist, C. W. (2023). A review of data-driven approaches to predict train delays. Transportation Research Part C, 148, 104027. doi:10.1016/j.trc.2023.104027',
  'Spanninger, T., Trivella, A., Büchel, B., & Corman, F. (2022). A review of train delay prediction approaches. Journal of Rail Transport Planning & Management, 22, 100312. doi:10.1016/j.jrtpm.2022.100312',
  'Chen, T., & Guestrin, C. (2016). XGBoost: A scalable tree boosting system. KDD, 785–794. doi:10.1145/2939672.2939785',
  'Lundberg, S. M., & Lee, S.-I. (2017). A unified approach to interpreting model predictions. NeurIPS 30.',
  'yadavsaurabh. Indian Railways Runs dataset. Hugging Face Datasets. GPL-3.0 dataset card.',
  'SimPy contributors. SimPy 4 documentation: shared resources and discrete-event processes.'
 ];
 refs.forEach((r,i)=>{txt(s,String(i+1).padStart(2,'0'),82,157+i*68,44,28,15,C.teal,true);txt(s,r,138,155+i*68,1040,54,16,C.ink,false,{valign:'top'});});
}

await fs.mkdir(path.dirname(FINAL),{recursive:true});
await fs.mkdir(BUILD,{recursive:true});
const pptx=await PresentationFile.exportPptx(pres);
await pptx.save(DRAFT);
for(let i=0;i<pres.slides.items.length;i++){
  const slide=pres.slides.items[i];
  const blob=await pres.export({slide,format:'png',scale:1});
  await fs.writeFile(path.join(BUILD,`deck-slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await blob.arrayBuffer()));
}
console.log(JSON.stringify({draft:DRAFT,slides:pres.slides.items.length,final:FINAL}));
