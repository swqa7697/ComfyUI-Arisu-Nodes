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
.arisu-director .workspace{min-height:0;flex:1;display:flex}
.arisu-director .timeline{padding:16px;overflow:auto;scrollbar-width:thin;width:100%}
.arisu-director .count{margin-inline-start:6px;color:var(--accent);font-variant-numeric:tabular-nums}
.arisu-director .timeline-head{margin-bottom:12px}
.arisu-director .list{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(240px,100%),1fr));gap:10px}
.arisu-director .list button{display:grid;grid-template-columns:28px minmax(0,1fr);align-content:start;text-align:left;gap:5px 10px;width:100%;padding:14px;background:var(--panel);border:1px solid var(--edge);border-radius:8px}
.arisu-director .list .index{grid-row:span 3;display:grid;place-content:center;background:var(--well);border:1px solid var(--edge);border-radius:5px;height:28px;color:var(--muted);font-variant-numeric:tabular-nums;font-size:12px}
.arisu-director .list button[aria-pressed=true]{background:var(--tint);border-color:var(--accent)}
.arisu-director .list button[aria-pressed=true] .index{color:var(--base);background:var(--accent)}
.arisu-director .list .intent{font-size:14px;font-weight:600;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.arisu-director .list :is(.card-time,.card-detail){grid-column:2;font-size:12px;font-weight:400}
.arisu-director .card-bottom{grid-column:1/-1;display:flex;align-items:center;justify-content:space-between;gap:8px;border-top:1px solid var(--edge);padding-top:10px;margin-top:6px}
.arisu-director .card-edit{color:var(--accent);font-size:12px}
.arisu-director .empty-sequence{display:flex;flex-direction:column;align-items:flex-start;gap:12px;max-width:400px;margin:32px auto;padding:12px}
.arisu-director .empty-index{font-size:26px;font-variant-numeric:tabular-nums;color:var(--muted)}
.arisu-director .empty-sequence button{margin-top:6px}
.arisu-director .render-group{flex:none;border-top:1px solid var(--edge);padding:10px 16px;display:grid;gap:8px}
.arisu-director .render-group .meta{flex:1;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.arisu-director footer{padding:8px 14px;border-top:1px solid var(--edge);background:var(--panel)}
.arisu-director .status{flex:1;min-width:10ch;color:var(--muted);font-size:12px;overflow-wrap:anywhere}
:is(.arisu-director,.arisu-director-dialog) button:hover:enabled{background:var(--tint);border-color:var(--accent)}
:is(.arisu-director,.arisu-director-dialog) button:active:enabled{filter:brightness(.9)}
:is(.arisu-director,.arisu-director-dialog) :is(button,input,textarea,select,summary):focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.arisu-director-dialog video{display:block;width:100%;max-height:240px;margin-top:6px}
@container(max-width:565px){
 .arisu-director .timeline{padding:12px}
 .arisu-director .list{grid-template-columns:minmax(0,1fr)}
 .arisu-director .empty-sequence{margin:12px auto}
}
dialog.arisu-director-dialog{
 position:fixed;inset:0;margin:auto;width:min(860px,calc(100vw - 24px));max-height:calc(100dvh - 24px);overflow:hidden;
 padding:0;border:1px solid var(--line);border-radius:10px;background:var(--base);font-family:inherit
}
dialog.arisu-director-dialog.compact{width:min(640px,calc(100vw - 24px))}
dialog.arisu-director-dialog[open]{display:flex;flex-direction:column}
.arisu-director-dialog .dialog-head,.arisu-director-dialog .dialog-foot{flex:none;padding:10px 14px}
.arisu-director-dialog .dialog-head{border-bottom:1px solid var(--line)}
.arisu-director-dialog .dialog-title{display:grid;gap:4px;flex:1}
.arisu-director-dialog .dialog-title h2{font-size:15px;color:var(--fg-color,#eee)}
.arisu-director-dialog .dialog-close{width:32px;font-size:16px;line-height:1}
.arisu-director-dialog .dialog-foot{border-top:1px solid var(--line)}
.arisu-director-dialog .dialog-foot[hidden]{display:none}
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
.arisu-director-dialog .card.muted{--kind:var(--muted);background:var(--base);border-inline-start-color:var(--line);filter:grayscale(1);opacity:.75}
.arisu-director-dialog .card.muted .asset-info strong{text-decoration:line-through}
.arisu-director-dialog .range input{accent-color:var(--accent);padding:0;cursor:pointer;height:22px}
.arisu-director-dialog .range .bar span:last-child{color:var(--ink);font-variant-numeric:tabular-nums}
.arisu-director-dialog .library .card{grid-template-columns:auto minmax(135px,1fr) minmax(110px,.9fr) auto;align-items:center;gap:8px;padding:8px}
.arisu-director-dialog .asset-action{display:inline-grid;place-items:center;width:28px;height:30px;min-height:0;padding:0;background:transparent;border-color:transparent}
.arisu-director-dialog .asset-action .pi{font-size:14px}
.arisu-director-dialog .dialog-head .asset-action{width:32px;border-color:var(--line);background:var(--well)}
.arisu-director-dialog .asset-action:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.arisu-director-dialog .asset-handle{width:20px;cursor:grab;font-size:18px;color:var(--muted)}
.arisu-director-dialog .asset-handle:active{cursor:grabbing}
.arisu-director-dialog .library [data-dragging]{opacity:.5}
.arisu-director-dialog .library [data-drop=before]{box-shadow:0 -3px var(--accent)}
.arisu-director-dialog .library [data-drop=after]{box-shadow:0 3px var(--accent)}
.arisu-director-dialog .library .mute[aria-pressed=false]{color:var(--kind)}
.arisu-director-dialog .library .mute .pi-circle-fill{font-size:10px}
.arisu-director-dialog .library .media-preview{position:relative}
.arisu-director-dialog .library .media-preview .pi{position:absolute;right:0;bottom:0;padding:3px;font-size:9px;color:var(--ink);background:var(--well);border-start-start-radius:3px}
.arisu-director-dialog .asset-title{display:grid;grid-template-columns:66px minmax(0,1fr);gap:10px}
.arisu-director-dialog .asset-info{display:grid;gap:2px}
.arisu-director-dialog strong{overflow-wrap:anywhere}
.arisu-director-dialog .media-kind{color:var(--kind);text-transform:capitalize}
.arisu-director-dialog .media-preview{display:grid;justify-items:stretch;overflow:hidden;padding:0;font-size:11px}
.arisu-director-dialog .media-preview>span:last-child{padding:2px 0}
.arisu-director-dialog .asset-thumb{width:100%;height:40px;object-fit:contain;background:color-mix(in srgb,var(--kind) 12%,var(--base))}
.arisu-director-dialog .asset-thumb.audio{display:grid;place-items:center;color:var(--kind);font-size:19px}
.arisu-director-dialog .asset-thumb.audio svg{width:19px;height:19px}
.arisu-director-dialog .card-tools{display:flex;align-items:center;gap:1px}
.arisu-director-dialog .empty-library{display:grid;place-items:center;text-align:center;min-height:100px;padding:12px;background:var(--well);border:1px solid var(--edge);border-radius:4px}
.arisu-director-dialog .check{display:inline-flex;align-items:center;gap:6px;cursor:pointer}
.arisu-director-dialog .current-prompt{white-space:pre-wrap;max-height:18dvh;overflow:auto;background:var(--panel);padding:10px 12px;border-inline-start:2px solid var(--accent)}
.arisu-director-dialog details{border-top:1px solid var(--edge);padding-top:8px}
.arisu-director-dialog details p{white-space:pre-wrap;margin-block-start:6px}
.arisu-director-dialog.segment-dialog{height:min(650px,calc(100dvh - 24px))}
.arisu-director-dialog.segment-dialog .dialog-head{padding:16px 20px;align-items:flex-start}
.arisu-director-dialog.segment-dialog .dialog-body{flex:1;padding:20px;gap:18px}
.arisu-director-dialog.segment-dialog .dialog-title h2{font-size:18px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.arisu-director-dialog .editor-tabs{display:flex;flex:none;gap:4px;padding:0 16px;border-bottom:1px solid var(--edge);background:var(--panel)}
.arisu-director-dialog .editor-tabs button{background:transparent;border:0;border-bottom:2px solid transparent;border-radius:0;padding:12px 10px;font-weight:550}
.arisu-director-dialog .editor-tabs button[aria-selected=true]{border-bottom-color:var(--accent);color:var(--accent)}
.arisu-director-dialog .prompt textarea{height:250px;min-height:150px}
.arisu-director-dialog .revision-request textarea{height:160px;min-height:100px}
.arisu-director-dialog .prompt>span{font-size:13px;font-weight:600;color:var(--ink)}
.arisu-director-dialog.segment-dialog .columns{gap:24px}
.arisu-director-dialog.segment-dialog .columns>:nth-child(2){padding-inline-start:24px}
.arisu-director-dialog.segment-dialog .field{gap:6px}
.arisu-director-dialog.segment-dialog .current-prompt{border:1px solid var(--edge);border-radius:6px}
@media(max-width:580px){
 .arisu-director-dialog .editor-tabs{padding:0 8px;gap:0}
 .arisu-director-dialog .editor-tabs button{flex:1;padding:10px 4px;font-size:11px}
 .arisu-director-dialog.segment-dialog .dialog-body{padding:14px}

 .arisu-director-dialog .library .card{grid-template-columns:auto minmax(0,1fr) auto}
 .arisu-director-dialog .library .field{grid-column:2/-1;grid-row:2}
 .arisu-director-dialog .card-tools{grid-column:3;grid-row:1}
}
@media(max-width:640px){
 .arisu-director-dialog .columns{grid-template-columns:minmax(0,1fr)}
 .arisu-director-dialog .columns>:nth-child(2),.arisu-director-dialog.segment-dialog .columns>:nth-child(2){border-inline-start:0;padding:12px 0 0;border-top:1px solid var(--edge)}
}
`;
