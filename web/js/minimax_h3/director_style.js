// The workspace responds to the node's width, independently of canvas zoom.
export const DIRECTOR_STYLE = `
:is(.arisu-director,.arisu-director-dialog){
 --base:var(--comfy-menu-bg,#181818);--panel:color-mix(in srgb,var(--base),var(--fg-color,#ddd) 5%);
 --well:var(--comfy-input-bg,#222);--line:var(--border-color,#4b4b4b);--edge:color-mix(in srgb,var(--base),var(--fg-color,#ddd) 18%);
 --ink:var(--input-text,#ddd);--muted:color-mix(in srgb,var(--ink) 74%,var(--base));
 --accent:var(--arisu-blue,#a8bfdc);--tint:color-mix(in srgb,var(--base),var(--accent) 13%);
 color:var(--ink);font:13px/1.45 system-ui,sans-serif;box-sizing:border-box;color-scheme:inherit;
}
:is(.arisu-director,.arisu-director-dialog) *{box-sizing:border-box;min-width:0}
:is(.arisu-director,.arisu-director-dialog) :is(h2,h3,h4,p){margin:0;overflow-wrap:anywhere}
:is(.arisu-director,.arisu-director-dialog) h2{font-size:19px;line-height:1.25;font-weight:650}
:is(.arisu-director,.arisu-director-dialog) h3{font-size:15px;font-weight:650}
:is(.arisu-director,.arisu-director-dialog) :is(small,.meta){font-size:12px;color:var(--muted);overflow-wrap:anywhere}
:is(.arisu-director,.arisu-director-dialog) :is(button,select,input,textarea){font:inherit;color:inherit;background:var(--well);border:1px solid var(--line);border-radius:5px;padding:6px 9px}
:is(.arisu-director,.arisu-director-dialog) :is(button,select,summary){cursor:pointer}
:is(.arisu-director,.arisu-director-dialog) button{font-size:12px;font-weight:550;line-height:1.4;min-height:30px;overflow-wrap:anywhere}
:is(.arisu-director,.arisu-director-dialog) :is(.actions,.asset-title,.bar){display:flex;align-items:center;gap:6px;flex-wrap:wrap}
:is(.arisu-director,.arisu-director-dialog) .bar{justify-content:space-between;gap:8px}
:is(.arisu-director,.arisu-director-dialog) .field{display:grid;align-content:start;gap:4px}
:is(.arisu-director,.arisu-director-dialog) .field>span{color:var(--muted);font-size:12px;font-weight:550}
:is(.arisu-director,.arisu-director-dialog) .field>:is(textarea,input,select){width:100%}
:is(.arisu-director,.arisu-director-dialog) textarea{min-height:68px;resize:vertical;line-height:1.55}
:is(.arisu-director,.arisu-director-dialog) .stack{display:grid;align-content:start;gap:12px}
.arisu-director{display:flex;flex-direction:column;width:100%;height:100%;min-height:0;background:var(--base);container-type:inline-size;overflow:hidden}
.arisu-director .film-head{padding:13px 14px;border-bottom:1px solid var(--edge);background:var(--panel)}
.arisu-director .film-head>div:first-child{flex:1 1 210px}
.arisu-director .film-head .meta{overflow:hidden;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;margin-top:3px;font-variant-numeric:tabular-nums}
.arisu-director .workspace{display:grid;grid-template-columns:minmax(152px,.85fr) minmax(0,1.95fr);min-height:0;flex:1}
.arisu-director .timeline,.arisu-director .editor{padding:14px;overflow:auto;scrollbar-width:thin}
.arisu-director .timeline{position:relative;border-right:1px solid var(--edge);background:var(--panel)}
.arisu-director .count{margin-inline-start:6px;color:var(--accent);font-variant-numeric:tabular-nums}
.arisu-director .timeline-head{margin-bottom:10px}
.arisu-director .list{display:grid;gap:5px}
.arisu-director .list button{display:grid;grid-template-columns:24px minmax(0,1fr);align-items:start;text-align:left;gap:1px 7px;width:100%;padding:9px 7px;background:transparent;border:1px solid transparent}
.arisu-director .list .index{grid-row:span 3;display:grid;place-content:center;background:var(--well);border:1px solid var(--edge);border-radius:4px;height:23px;color:var(--muted);font-variant-numeric:tabular-nums;font-size:11px}
.arisu-director .list button[aria-pressed=true]{background:var(--tint);border-color:color-mix(in srgb,var(--accent) 65%,var(--base))}
.arisu-director .list button[aria-pressed=true] .index{color:var(--base);background:var(--accent)}
.arisu-director .list .intent{overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.arisu-director .list small{font-size:11px;font-weight:400}
.arisu-director .editor{display:flex;flex-direction:column;gap:13px}
.arisu-director .editor .prompt textarea{min-height:100px;height:118px}
.arisu-director .editor .segment-head{display:grid;gap:3px}
.arisu-director .editor .segment-head h2{font-size:18px}
.arisu-director .continuity{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(135px,100%),1fr));gap:10px;margin:0;padding:8px 10px;background:var(--panel);border-inline-start:2px solid var(--accent)}
.arisu-director .continuity dt{font-size:11px;color:var(--muted)}
.arisu-director .continuity dd{font-size:12px;margin:2px 0 0;overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.arisu-director .render-group{border-top:1px solid var(--edge);padding-top:10px;display:grid;gap:7px}
.arisu-director footer{padding:8px 14px;border-top:1px solid var(--edge);background:var(--panel)}
.arisu-director .status{flex:1;min-width:10ch;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
.arisu-director video{display:block;width:100%;max-height:240px;margin-top:6px}
@container(max-width:565px){
 .arisu-director .workspace{grid-template-columns:minmax(0,1fr);grid-template-rows:auto minmax(0,1fr)}
 .arisu-director .timeline{padding:8px 12px;border-right:0;border-bottom:1px solid var(--edge);max-height:144px}
 .arisu-director .timeline-head{margin-bottom:5px}
 .arisu-director .list{grid-template-columns:repeat(auto-fit,minmax(min(150px,100%),1fr))}
 .arisu-director .editor{padding:12px}
}
dialog.arisu-director-dialog{
 position:fixed;inset:0;margin:auto;width:min(860px,calc(100vw - 24px));max-height:calc(100dvh - 24px);overflow:hidden;
 padding:0;border:1px solid var(--line);background:var(--base);font-family:inherit
}
dialog.arisu-director-dialog.compact{width:min(640px,calc(100vw - 24px))}
dialog.arisu-director-dialog[open]{display:flex;flex-direction:column}
.arisu-director-dialog .dialog-head,.arisu-director-dialog .dialog-foot{flex:none;padding:10px 14px}
.arisu-director-dialog .dialog-head{border-bottom:1px solid var(--line)}
.arisu-director-dialog .dialog-title{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.arisu-director-dialog .dialog-title h2{font-size:15px;color:var(--fg-color,#eee)}
.arisu-director-dialog .dialog-close{width:32px;font-size:16px;line-height:1}
.arisu-director-dialog .dialog-foot{border-top:1px solid var(--line)}
.arisu-director-dialog .dialog-body{padding:16px;min-height:0;overflow:auto;scrollbar-width:thin;overscroll-behavior:contain}
.arisu-director-dialog .columns{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:18px}
.arisu-director-dialog .columns>:nth-child(2){border-inline-start:1px solid var(--edge);padding-inline-start:18px}
.arisu-director-dialog .stack{gap:10px}
.arisu-director-dialog h3{color:var(--fg-color,#eee);font-size:13px}
.arisu-director-dialog .stack>section+section{padding-top:12px;border-top:1px solid var(--edge)}
.arisu-director-dialog .paired{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(135px,100%),1fr));gap:8px}
.arisu-director-dialog .field>span,.arisu-director-dialog button{font-weight:400}
.arisu-director-dialog .film-requirements{align-self:stretch;grid-template-rows:auto 1fr}
.arisu-director-dialog .film-requirements>span{font-size:13px;font-weight:650;color:var(--fg-color,#eee)}
.arisu-director-dialog .dialog-foot .field{display:flex;align-items:center;gap:6px}
.arisu-director-dialog .dialog-foot .field>select{width:auto}
.arisu-director-dialog .library{display:grid;gap:8px}
.arisu-director-dialog .card{
 --kind:var(--edge);display:grid;gap:10px;padding:10px 12px;background:var(--panel);border:1px solid var(--edge);
 border-inline-start:3px solid var(--kind);border-radius:4px
}
.arisu-director-dialog .card[data-kind=image]{--kind:var(--arisu-image)}
.arisu-director-dialog .card[data-kind=video]{--kind:var(--arisu-video)}
.arisu-director-dialog .card[data-kind=audio]{--kind:var(--arisu-audio)}
.arisu-director-dialog .library .card{grid-template-columns:minmax(0,1fr) minmax(0,1fr);align-items:center}
.arisu-director-dialog .asset-title{display:grid;grid-template-columns:66px minmax(0,1fr);gap:10px}
.arisu-director-dialog .asset-info{display:grid;gap:2px}
.arisu-director-dialog strong{overflow-wrap:anywhere}
.arisu-director-dialog .media-kind{color:var(--kind);text-transform:capitalize}
.arisu-director-dialog .media-preview{display:grid;justify-items:stretch;overflow:hidden;padding:0;font-size:11px}
.arisu-director-dialog .media-preview>span:last-child{padding:2px 0}
.arisu-director-dialog .asset-thumb{width:100%;height:40px;object-fit:contain;background:color-mix(in srgb,var(--kind) 12%,var(--base))}
.arisu-director-dialog .asset-thumb.audio{display:grid;place-items:center;color:var(--kind);font-size:19px}
.arisu-director-dialog .card-tools{grid-column:1/-1;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px}
.arisu-director-dialog .card.muted .asset-info strong{text-decoration:line-through}
.arisu-director-dialog .empty-library{display:grid;place-items:center;text-align:center;min-height:100px;padding:12px;background:var(--well);border:1px solid var(--edge);border-radius:4px}
.arisu-director-dialog .check{display:inline-flex;align-items:center;gap:6px;cursor:pointer}
.arisu-director-dialog .current-prompt{white-space:pre-wrap;max-height:25dvh;overflow:auto;background:var(--panel);padding:10px 12px;border-inline-start:2px solid var(--accent)}
.arisu-director-dialog details{border-top:1px solid var(--edge);padding-top:8px}
.arisu-director-dialog details p{white-space:pre-wrap;margin-block-start:6px}
@media(max-width:640px){
 .arisu-director-dialog .columns,.arisu-director-dialog .library .card{grid-template-columns:minmax(0,1fr)}
 .arisu-director-dialog .columns>:nth-child(2){border-inline-start:0;padding:12px 0 0;border-top:1px solid var(--edge)}
}
`;
