import { useEffect, useState, ReactNode } from "react";
import { ArrowLeft, ArrowRight, CheckCircle2, ChevronDown, Clock, Crosshair, ExternalLink, LogOut, Loader2, MapPin, Search, Sparkles, Target, TrendingUp } from "lucide-react";
import { api, ApiError } from "../api";

const PROPERTY_TYPES = [
  { value: "land", label: "🌳 Land / Plot" },
  { value: "flat", label: "🏢 Flat / Apartment" },
  { value: "villa", label: "🏡 Villa" },
  { value: "independent_house", label: "🏠 Independent House" },
  { value: "commercial", label: "🏬 Commercial Property" },
];
const BHK = ["1 BHK", "2 BHK", "3 BHK", "4 BHK", "5+ BHK"];
const STATUS = ["Ready to Move", "Under Construction", "Resale"];
const UNITS = ["sq ft", "sq yd", "sq m", "acre", "hectare", "cent", "gunta", "marla", "bigha"];
const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "CAD", "AUD", "SGD", "JPY"];

type Place = { display_name: string; lat: string; lon: string };
type AffordOption = {category:string;label:string;available:boolean;estimated_price?:number|null;estimated_price_per_sqft?:number|null;estimated_area_sqft?:number|null;estimated_area_display?:Record<string,number>;property_status?:string|null;source_count?:number;observation_count?:number;confidence?:string|null;note?:string|null};
export type Result = { location:string; property_type:string; bhk?:string; property_status?:string; price_per_unit?:number; unit?:string; currency:string; estimated_total_price?:number|null; source_summary?:string; sources:string[]; source_count?:number; observation_count?:number; confidence?:string; average_price?:number|null; min_price?:number|null; max_price?:number|null; average_price_per_sqft?:number|null; typical_area_min?:number|null; typical_area_max?:number|null; sample_size?:number|null; market_trend?:string|null; model_used?:string|null; ml_metrics?:Record<string,any>; budget?:number; affordable_area?:number|null; affordable_area_unit?:string|null; equivalent?:Record<string,number>; options?:AffordOption[]; notes?:string; historical_prices?:Array<{year:number;price_per_sqft:number}>; forecast_prices?:Array<{year:number;predicted_price_per_sqft:number}>; historical_query?:string; historical_sources?:string[]; };
type Mode = "price" | "affordability";

function money(n:number, c:string){ try{return new Intl.NumberFormat("en-IN",{style:"currency",currency:c,maximumFractionDigits:n<1000?2:0}).format(n)}catch{return `${c} ${Math.round(n).toLocaleString("en-IN")}`}}
function num(n:number){return Number(n).toLocaleString("en-IN",{maximumFractionDigits:2})}
function labelType(v:string){return PROPERTY_TYPES.find(x=>x.value===v)?.label.replace(/^\S+\s/,'')||v}
function Select({value,onChange,options}:{value:string;onChange:(v:string)=>void;options:string[]}){return <div className="select-box"><select value={value} onChange={e=>onChange(e.target.value)}>{options.map(x=><option key={x} value={x}>{x}</option>)}</select><ChevronDown size={16}/></div>}

export default function Estimator({token,userName,onLogout,onOpenHistory,initialResult}:{token:string;userName:string;onLogout:()=>void;onOpenHistory:()=>void;initialResult?:{result:Result;mode:Mode}|null}){
 const [propertyType,setPropertyType]=useState("land"); const [mode,setMode]=useState<Mode>(initialResult?.mode||"price"); const [location,setLocation]=useState(""); const [places,setPlaces]=useState<Place[]>([]); const [coords,setCoords]=useState<{lat:number;lon:number}|null>(null); const [bhk,setBhk]=useState("2 BHK"); const [status,setStatus]=useState("Ready to Move"); const [area,setArea]=useState("1200"); const [unit,setUnit]=useState("sq ft"); const [currency,setCurrency]=useState("INR"); const [budget,setBudget]=useState("5000000"); const [busy,setBusy]=useState(false); const [geoBusy,setGeoBusy]=useState(false); const [error,setError]=useState(""); const [result,setResult]=useState<Result|null>(initialResult?.result||null);
 useEffect(()=>{const t=setTimeout(async()=>{if(location.trim().length<3){setPlaces([]);return} try{const r=await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=5&q=${encodeURIComponent(location)}`,{headers:{Accept:"application/json"}});if(r.ok)setPlaces(await r.json())}catch{}},400);return()=>clearTimeout(t)},[location]);
 const choose=(p:Place)=>{setLocation(p.display_name);setCoords({lat:+p.lat,lon:+p.lon});setPlaces([])};
 const current=()=>{if(!navigator.geolocation){setError("Geolocation is not supported.");return}setGeoBusy(true);navigator.geolocation.getCurrentPosition(async p=>{setCoords({lat:p.coords.latitude,lon:p.coords.longitude});try{const r=await fetch(`https://nominatim.openstreetmap.org/reverse?format=json&lat=${p.coords.latitude}&lon=${p.coords.longitude}`);const d=await r.json();setLocation(d.display_name||`${p.coords.latitude}, ${p.coords.longitude}`)}catch{setLocation(`${p.coords.latitude.toFixed(5)}, ${p.coords.longitude.toFixed(5)}`)}finally{setGeoBusy(false)}},()=>{setGeoBusy(false);setError("Location permission was denied. Search for a location instead.")})};
 async function analyze(){setError("");if(!location.trim()){setError("Please search and select a location.");return}setBusy(true);try{const body:any={property_type:propertyType,location,currency};if(mode==="price"){if(propertyType!=="land"){body.bhk=bhk;body.property_status=status}body.area=+area;body.area_unit=unit}else{if(propertyType!=="land" && propertyType!=="commercial"){body.property_status=status}body.budget=+budget}const endpoint=mode==="price" ? "/property-price" : "/affordability";const d=await api<Result>(endpoint,{method:"POST",body,token});if(mode==="price" && !(d.price_per_unit!>0) && !(d.average_price!&&d.average_price>0))throw Error("No usable property-price evidence was returned.");if(mode==="affordability" && !d.options?.length && !(d.affordable_area!>0))throw Error("No usable affordability evidence was returned.");setResult(d)}catch(e:any){if(e instanceof ApiError && e.status===401){onLogout();return}setError(e.message||"Could not connect to LandWise AI.")}finally{setBusy(false)}}
 const nav=<div className="topbar"><div className="brand"><span className="brand-icon"><Sparkles size={15}/></span><span>LandWise <b>AI</b></span></div><div className="user-nav"><button className="ghost-btn" onClick={onOpenHistory}><Clock size={13}/> History</button><span className="user-chip">{userName}</span><button className="ghost-btn" onClick={onLogout}><LogOut size={13}/></button></div></div>;
 if(result)return mode==="affordability"?<AffordabilityResults result={result} currency={currency} coords={coords} onBack={()=>setResult(null)} nav={nav}/>:<Results result={result} mode={mode} area={area} unit={unit} currency={currency} coords={coords} onBack={()=>setResult(null)} nav={nav}/>;
 return <main className="app"><div className="background-glow glow-a"/><div className="background-glow glow-b"/><div className="dashboard">{nav}<div className="eyebrow">PROPERTY PRICE INTELLIGENCE</div><h1>{mode==="price"?"Find a property estimate":"Find what you can afford"}</h1><p className="subtitle">Evidence-based property estimates using Tavily web evidence and historical ML.</p>
 <div className="property-grid">{PROPERTY_TYPES.map(p=><button key={p.value} className={`property-card ${propertyType===p.value?"active":""}`} onClick={()=>setPropertyType(p.value)}>{p.label}</button>)}</div>
 <div className="tabs"><button className={mode==="price"?"tab active":"tab"} onClick={()=>setMode("price")}><span>$</span> Price</button><button className={mode==="affordability"?"tab active":"tab"} onClick={()=>setMode("affordability")}><Target size={14}/> Affordability</button></div>
 <div className="field"><label>LOCATION</label><div className="search-box"><Search size={16}/><input value={location} onChange={e=>{setLocation(e.target.value);setCoords(null)}} placeholder="Search city, locality, address or landmark..."/><button onClick={current}>{geoBusy?<Loader2 size={15} className="spin"/>:<Crosshair size={15}/>}</button></div>{places.length>0&&<div className="place-list">{places.map((p,i)=><button key={i} onClick={()=>choose(p)}><MapPin size={14}/><span>{p.display_name}</span></button>)}</div>}<button className="current-location" onClick={current}><MapPin size={13}/> Use my current location</button></div>
 {mode==="price"&&propertyType!=="land"&&<div className="two-fields"><div className="field"><label>BHK</label><Select value={bhk} onChange={setBhk} options={BHK}/></div><div className="field"><label>PROPERTY STATUS</label><Select value={status} onChange={setStatus} options={STATUS}/></div></div>}{mode==="affordability"&&propertyType!=="land"&&propertyType!=="commercial"&&<div className="field"><label>PROPERTY STATUS</label><Select value={status} onChange={setStatus} options={STATUS}/></div>}
 {mode==="price"?<><div className="two-fields"><div className="field"><label>{propertyType==="land"?"LAND AREA":"AREA (OPTIONAL)"}</label><input className="control" type="number" min="0" value={area} onChange={e=>setArea(e.target.value)}/></div><div className="field"><label>AREA UNIT</label><Select value={unit} onChange={setUnit} options={UNITS}/></div></div></>:<div className="field"><label>BUDGET</label><input className="control" type="number" min="0" value={budget} onChange={e=>setBudget(e.target.value)}/></div>}
 <div className="field"><label>CURRENCY</label><Select value={currency} onChange={setCurrency} options={CURRENCIES}/></div><button className="analyze" disabled={busy} onClick={analyze}>{busy?<><Loader2 size={17} className="spin"/> Collecting Tavily market evidence...</>:<>{mode==="price"?"Analyze property":"Check affordability"}<ArrowRight size={18}/></>}</button>{error&&<div className="error">{error}</div>}<div className="powered"><Sparkles size={13}/> Tavily search <b>+</b> source extraction <b>+</b> validated comparables <b>+</b> ML</div></div></main>
}

function AffordabilityResults({result:r,currency,coords,onBack,nav}:{result:Result;currency:string;coords:{lat:number;lon:number}|null;onBack:()=>void;nav:ReactNode}){
 const map=coords?`https://www.openstreetmap.org/export/embed.html?bbox=${coords.lon-.12}%2C${coords.lat-.08}%2C${coords.lon+.12}%2C${coords.lat+.08}&layer=mapnik&marker=${coords.lat}%2C${coords.lon}`:"";
 const isLand=r.property_type==="land";
 const options=r.options||[];
 const affordableUnits=["sq ft","sq yd","sq m","acre","hectare","cent","gunta","marla","bigha"];
 const [affordableUnit,setAffordableUnit]=useState(r.affordable_area_unit||"sq ft");
 const affordableValue=isLand ? (r.equivalent?.[affordableUnit] ?? (affordableUnit===(r.affordable_area_unit||"sq ft") ? r.affordable_area : null)) : null;
 return <main className="results-page"><div className="results-shell">{nav}
  <div className="results-head"><button className="back-button" onClick={onBack}><ArrowLeft size={16}/> Back to affordability</button></div>
  <div className="result-title"><div><div className="eyebrow">AFFORDABILITY ANALYSIS</div><h1>What your budget can get</h1><div className="result-location"><MapPin size={16}/>{r.location}</div></div><div className="analysis-chip"><CheckCircle2 size={14}/> Evidence analyzed</div></div>
  <section className="metric-grid">
   <Metric title="Budget" value={money(r.budget||0,r.currency||currency)} caption="your available budget" accent/>
   {isLand?<div className="metric accent"><span>Affordable Area</span><strong>{affordableValue!=null?num(affordableValue):"—"} {affordableUnit}</strong><small>based on current validated price</small></div>:<Metric title="Property type" value={labelType(r.property_type)} caption={r.property_status||"scenario analysis"}/>}
   {isLand?<Metric title="Equivalent" value={`${num(r.equivalent?.["acre"]||0)} acre`} caption={`${num(r.equivalent?.["sq yd"]||0)} sq yd`}/>:<Metric title="Scenarios" value={`${options.length}`} caption="market segments evaluated"/>}
  </section>
  <section className="content-grid">
   <div className="left-column">
    <div className="panel map-panel"><div className="panel-title"><MapPin size={16}/> Location map</div>{map?<iframe title="Location map" src={map}/>:<div className="map-empty"><MapPin size={24}/> Coordinates unavailable</div>}</div>
    <div className="panel"><div className="panel-title"><Target size={16}/> {isLand?"Land area equivalents":"Budget scenarios"}</div>
      {isLand?<><div className="two-fields result-unit-selector"><div className="field"><label>UNIT</label><Select value={affordableUnit} onChange={setAffordableUnit} options={affordableUnits}/></div></div><div className="equivalent-row"><span>Affordable Area</span><strong>{affordableValue!=null?`${num(affordableValue)} ${affordableUnit}`:"—"}</strong></div><div className="equivalent-list">{Object.entries(r.equivalent||{}).map(([u,v])=><div className={`equivalent-row ${u===affordableUnit?"selected-equivalent":""}`} key={u}><span>{u}</span><strong>{num(v as number)} {u}</strong></div>)}</div></>:
      <div className="equivalent-list">{options.map(o=><div className={`afford-card ${o.available?"available":"unavailable"}`} key={o.label}><div><strong>{o.label}</strong><span>{o.property_status||""}</span></div><b>{o.available?"Within budget":"Above budget"}</b><small>{o.estimated_price?money(o.estimated_price,r.currency):"No validated estimate"}{o.estimated_area_sqft?` • ${num(o.estimated_area_sqft)} sq ft`: ""}</small><p>{o.note}</p></div>)}</div>}
    </div>
   </div>
   <div className="right-column">
    <div className="panel ai-panel"><div className="panel-title"><Sparkles size={16}/> Evidence + affordability analysis</div><div className="analysis-status"><span/> Current web evidence analyzed</div><p>{r.notes||"Evidence-based affordability analysis."}</p>{!isLand&&r.property_status&&<div className="info-row"><span>Property status</span><b>{r.property_status}</b></div>}<div className="info-row"><span>Budget</span><b>{money(r.budget||0,r.currency)}</b></div><div className="info-row"><span>Sources</span><b>{r.sources?.length||0}</b></div></div>
    <div className="panel"><div className="panel-title">Sources</div><div className="source-list">{(r.sources||[]).slice(0,8).map((s,i)=><a key={i} href={s} target="_blank" rel="noreferrer"><span>Web source {i+1}</span><ExternalLink size={13}/></a>)}</div></div>
   </div>
  </section>
 </div></main>
}

function Results({result:r,mode,area,unit,currency,coords,onBack,nav}:{result:Result;mode:Mode;area:string;unit:string;currency:string;coords:{lat:number;lon:number}|null;onBack:()=>void;nav:ReactNode}){
 const map=coords?`https://www.openstreetmap.org/export/embed.html?bbox=${coords.lon-.12}%2C${coords.lat-.08}%2C${coords.lon+.12}%2C${coords.lat+.08}&layer=mapnik&marker=${coords.lat}%2C${coords.lon}`:"";
 const avg=r.average_price||r.price_per_unit||r.average_price_per_sqft||0;
 const total=mode==="price"?(r.estimated_total_price ?? (r.price_per_unit||0)*+area):avg;
 const historical=r.historical_prices||[];
 const forecast=r.forecast_prices||[];
 return <main className="results-page"><div className="results-shell">{nav}
  <div className="results-head"><button className="back-button" onClick={onBack}><ArrowLeft size={16}/> Back to search</button></div>
  <div className="result-title"><div><div className="eyebrow">PROPERTY PRICE ANALYSIS</div><h1>{r.bhk?r.bhk+" ":""}{labelType(r.property_type)} Estimate</h1><div className="result-location"><MapPin size={16}/>{r.location}</div></div><div className="analysis-chip"><CheckCircle2 size={14}/> Analysis ready</div></div>
  <section className="metric-grid">
   <Metric title={mode==="price"?"Estimated Price":"Average Price"} value={money(total,r.currency||currency)} caption={mode==="price"?`for ${area} ${unit}`:"typical property estimate"} accent/>
   <Metric title="Price / Sq Ft" value={r.average_price_per_sqft?money(r.average_price_per_sqft,r.currency):"—"} caption={r.confidence?`Tavily evidence confidence: ${r.confidence}`:"Evidence-based estimate"}/>
   <Metric title="Forecast Horizon" value={forecast.length?`${forecast[0].year}–${forecast[forecast.length-1].year}`:"—"} caption={forecast.length?"5-year trend projection":"Not enough historical data"}/>
  </section>
  <section className="content-grid">
   <div className="left-column">
    <div className="panel map-panel"><div className="panel-title"><MapPin size={16}/> Location map</div>{map?<iframe title="Location map" src={map}/>:<div className="map-empty"><MapPin size={24}/> Coordinates unavailable</div>}</div>
    <div className="panel"><div className="panel-title"><TrendingUp size={16}/> 4-year historical land prices</div>
      {historical.length?<div className="equivalent-list">{historical.map(row=><div className="equivalent-row" key={row.year}><span>{row.year}</span><strong>{money(row.price_per_sqft,r.currency)}/sq ft</strong></div>)}</div>:<p>No year-wise values were returned by the Tavily history search.</p>}
    </div>
    <div className="panel"><div className="panel-title"><TrendingUp size={16}/> Next 5 years — calculated trend</div>
      {forecast.length?<div className="equivalent-list">{forecast.map(row=><div className="equivalent-row" key={row.year}><span>{row.year}</span><strong>{money(row.predicted_price_per_sqft,r.currency)}/sq ft</strong></div>)}</div>:<p>Forecast unavailable because fewer than two historical observations were extracted.</p>}
      <small>Projection is a mathematical trend from the extracted annual series; it is not a guaranteed future market price.</small>
    </div>
   </div>
   <div className="right-column">
    <div className="panel ai-panel"><div className="panel-title"><Sparkles size={16}/> Tavily History + ML Forecast</div><div className="analysis-status"><span/> Tavily evidence analyzed</div><p>{r.source_summary}</p>
      <div className="info-row"><span>Current price</span><b>{r.average_price_per_sqft?`${money(r.average_price_per_sqft,r.currency)}/sq ft`:"—"}</b></div>
      <div className="info-row"><span>Historical points</span><b>{historical.length}</b></div>
      <div className="info-row"><span>Forecast points</span><b>{forecast.length}</b></div>
      {r.model_used&&<div className="info-row"><span>Model</span><b>{r.model_used}</b></div>}
    </div>
    {r.historical_sources?.length?<div className="panel"><div className="panel-title">Tavily historical sources</div><div className="source-list">{r.historical_sources.slice(0,8).map((s,i)=><a key={i} href={s} target="_blank" rel="noreferrer"><span>History source {i+1}</span><ExternalLink size={13}/></a>)}</div></div>:null}
    <div className="panel"><div className="panel-title">Extraction note</div><p>LandWise sends the requested year-wise prompt to Tavily, normalizes the returned annual values to ₹/sq ft, and runs a small-sample Bayesian Ridge ML forecast. Google Search and Google AI Overview are not used in this flow.</p></div>
   </div>
  </section>
 </div></main>}
function Metric({title,value,caption,accent=false}:{title:string;value:string;caption:string;accent?:boolean}){return <div className={`metric ${accent?"accent":""}`}><span>{title}</span><strong>{value}</strong><small>{caption}</small></div>}
