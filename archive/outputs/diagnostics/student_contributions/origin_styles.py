from pathlib import Path
root=Path(__file__).parent
p=root/'graph_view.html'
s=p.read_text(encoding='utf-8')
s=s.replace("class:'edge-caption',tabindex", "class:'edge-caption'+(e.origin==='student'?' student-contribution':''),tabindex")
s=s.replace("class:'node',tabindex", "class:'node'+(n.origin==='student'?' student-contribution':''),tabindex")
s=s.replace('</style>', '.edge-caption.student-contribution rect,.node.student-contribution circle{stroke:#f472b6;stroke-width:3px}</style>', 1)
p.write_text(s,encoding='utf-8')
p=root/'professor.js'
s=p.read_text(encoding='utf-8').replace("['#bf9bff','Manual']", "['#bf9bff','Manual'],['#f472b6','Student contributions']")
s=s.replace("$('graph-legend').replaceChildren(...legends", "if(mode!=='explore')legends.push(['#f472b6','Pink outline: student contribution']);\n $('graph-legend').replaceChildren(...legends")
p.write_text(s,encoding='utf-8')
