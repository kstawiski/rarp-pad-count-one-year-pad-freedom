source('scripts/plot_common.R')
pA=blank_panel('A  Patient selection',7.0)
# v6: taller boxes give the spine arrowheads clear space above each label.
bh=.31
flowbox=function(x0,x1,y,fill='white'){
 annotate('rect',xmin=x0,xmax=x1,ymin=y-bh,ymax=y+bh,fill=fill,colour='#1a1a1a',linewidth=.45)
}
# Spine counts come from the frozen ladder; complements are exact arithmetic
# differences branching from the divided population (100=1497-1397
# non-robotic; 753=1397-644 without early status; 184=644-460 early pad-free;
# 234=460-226 without year status; 25=226-201 documentation states) and the
# 201 contrast denominator is the frozen ordered-comparison size.
ladder_rows=lapply(seq_along(d$ladder),function(i)list(d$ladder[[i]]$label,d$ladder[[i]]$count,7-i,NULL))
# v6 final: labels match the manuscript wording, and the 25 unclassifiable men leave at the
# 226-to-201 step rather than below the 201 box.
ladder_rows[[6]]=list('One pad vs two or more','201',1,NULL)
ladder_rows[[1]][[1]]='Patients in the database'
ladder_rows[[1]][[4]]=list('Non-robotic procedures','100')
ladder_rows[[2]][[4]]=list('No three-month assessment','753')
ladder_rows[[3]][[4]]=list('Pad-free at three months','184')
ladder_rows[[4]][[4]]=list('No one-year record','234')
ladder_rows[[5]][[4]]=list('Unclear or conflicting count','25')
# Draw the point marker for every pooled row, including the 0% conflicting group.
d$pooled=lapply(d$pooled,function(r){r$show_point=TRUE;r})
xc=(-109-8)/2
for(s in ladder_rows){
 y=s[[3]]
 fill=if(s[[2]]=='201')'#DCEAF5' else 'white'
 pA=pA+flowbox(-109,-8,y,fill)+
  text_at(-104,y,s[[1]])+
  text_at(-13,y,s[[2]],hjust=1,size=pt,face='bold')
 if(y>1)pA=pA+annotate('segment',x=xc,xend=xc,y=y-.24,yend=y-1+.24,linewidth=.45,colour='#1a1a1a',arrow=grid::arrow(length=unit(1.2,'mm'),type='closed'))
 comp=s[[4]]
 if(!is.null(comp))pA=pA+flowbox(8,96,y)+
  text_at(12,y,comp[[1]])+
  text_at(91,y,comp[[2]],hjust=1,size=pt,face='bold')+
  annotate('segment',x=-8,xend=8,y=y,yend=y,linewidth=.45,colour='#1a1a1a',arrow=grid::arrow(length=unit(1.2,'mm'),type='closed'))
}
Bheader=paste0('n/N   % (',d$meta$confidence,'% CI)')
# v7: part B shows the three-month pad-count gradient. Counts come from the frozen strengthening
# record; the one-pad, two-or-more and overall rows are the frozen Figure 1 rows and are checked
# against it. Unclear and conflicting counts are reported in Supplementary Table S2.
st <- jsonlite::fromJSON('/umed-projekty/PROSTATA_JOBCZYK2026_v2/manuscript1/evidence/STRENGTHENING_ANALYSES.json',simplifyVector=FALSE)
sig2b <- function(v){
 if(abs(v)<1e-12)return('0')
 e=floor(log10(abs(v)));q=10^(e-1)
 r=sign(v)*floor(abs(v)/q+0.5+1e-9)*q
 if(floor(log10(abs(r)))>e){q=10^e;r=sign(v)*floor(abs(v)/q+0.5+1e-9)*q}
 if(q>=1)sprintf('%d',as.integer(round(r))) else sprintf(paste0('%.',as.integer(round(-log10(q))),'f'),r)
}
wilson <- function(x,n){z=qnorm(.975);p=x/n;den=1+z^2/n;cc=(p+z^2/(2*n))/den;h=z*sqrt(p*(1-p)/n+z^2/(4*n^2))/den;c(max(0,cc-h),min(1,cc+h))}
grow <- function(x,n,label,kind){ci=wilson(x,n)
 list(label=label,kind=kind,estimate=100*x/n,lower=100*ci[1],upper=100*ci[2],show_interval=TRUE,show_point=TRUE,
  text=paste0(x,'/',n,'   ',sig2b(100*x/n),'% (',sig2b(100*ci[1]),'–',sig2b(100*ci[2]),')'))}
g=st$gradient
stopifnot(g$one$events==as.numeric(d$pooled[[1]]$numerator),g$one$n==as.numeric(d$pooled[[1]]$denominator),
 g$two$events+g$three_or_more$events+g$two_or_more_unseparated$events==as.numeric(d$pooled[[2]]$numerator),
 g$two$n+g$three_or_more$n+g$two_or_more_unseparated$n==as.numeric(d$pooled[[2]]$denominator))
# Rows follow the comparison: one pad, then all two-or-more users with their exactly-two and
# three-or-more subgroups indented beneath them.
Brows=list(grow(g$pad_free_at_three_months$events,g$pad_free_at_three_months$n,'No pads (pad-free at three months)','pad_free'),
 d$pooled[[1]],d$pooled[[2]],grow(g$two$events,g$two$n,'Exactly two pads','two_or_more'),
 grow(g$three_or_more$events,g$three_or_more$n,'Three or more pads','two_or_more'),d$pooled[[5]])
Brows[[2]]$label='One pad';Brows[[3]]$label='Two or more pads, all';Brows[[6]]$label='All men using pads'
Brows[[4]]$indent=TRUE;Brows[[5]]$indent=TRUE
pB=forest_block(Brows,'B  Pad freedom at one year by daily pad count at three months',c(7.0,6.0,5.0,4.0,3.0,1.5),header=Bheader,rule_at=2.25,axis_title='Documented pad freedom at one year (%)')
d$country=lapply(d$country,function(r){r$label=sub('^One ordinary pad documented','One pad',r$label);r$label=sub('^Two or more ordinary pads documented','Two or more pads',r$label);r})
pC=forest_country(d$country,'C  Documented pad freedom at one year within each country',header=Bheader,axis_title='Documented pad freedom at one year (%)')
pD=forest(d$contrasts,'D  Difference within each population, one pad minus two or more pads',c(3.4,2.4,1.4),contrast=TRUE,header=paste0('Percentage points (',d$meta$confidence,'% CI)'),axis_title='Difference (percentage points)',rule_at=2.9)
fig=wrap_plots(list(pA,pB,pC,pD),ncol=1,heights=c(56,72,70,48),guides='collect',axis_titles='collect')
export_figure(fig,list(pA,pB,pC,pD),'Figure1',232)
