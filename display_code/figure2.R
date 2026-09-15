source('scripts/plot_common.R')
# Main Figure 2 (v6, final external review).
# Part A groups the one-pad-minus-two-or-more difference by the source of uncertainty
# each analysis addresses. Part B shows how missing one-year outcomes could change the
# difference among men whose one-year window had closed before the source extracts.
# Every value is read at render time from the frozen evidence records.
EV <- '/umed-projekty/PROSTATA_JOBCZYK2026_v2/manuscript1/evidence/'
obs <- jsonlite::fromJSON(paste0(EV,'OBSERVED_STATUS_ESTIMATES.json'),simplifyVector=FALSE)
ph <- jsonlite::fromJSON(paste0(EV,'POSTHOC_TWOGROUP.json'),simplifyVector=FALSE)
sel <- jsonlite::fromJSON(paste0(EV,'SELECTION_FOLLOWUP_SENSITIVITY.json'),simplifyVector=FALSE)
clin <- jsonlite::fromJSON(paste0(EV,'CLINICAL_ADJUSTMENT.json'),simplifyVector=FALSE)
st <- jsonlite::fromJSON(paste0(EV,'STRENGTHENING_ANALYSES.json'),simplifyVector=FALSE)

# Two significant figures, rounded half up (precision decision D-P1).
sig2 <- function(v){
 if(abs(v)<1e-12)return('0')
 e=floor(log10(abs(v)));q=10^(e-1)
 r=sign(v)*floor(abs(v)/q+0.5+1e-9)*q
 if(floor(log10(abs(r)))>e){q=10^e;r=sign(v)*floor(abs(v)/q+0.5+1e-9)*q}
 s=if(q>=1)sprintf('%d',as.integer(round(r))) else sprintf(paste0('%.',as.integer(round(-log10(q))),'f'),r)
 sub('^-','−',s)
}
pct <- function(p)paste0(sig2(100*p),'%')
ci <- function(e,l,u)paste0(sig2(100*e),' (',sig2(100*l),'–',sig2(100*u),')')

row_obs <- function(k,label){
 c=obs$policies[[k]]$central_burden_contrast$central
 stopifnot(!is.null(c$group_a$numerator),!is.null(c$estimate))
 list(label=label,estimate=100*c$estimate,lower=100*c$lower,upper=100*c$upper,
  text=paste0(c$group_a$numerator,'/',c$group_a$denominator,' vs ',c$group_b$numerator,'/',c$group_b$denominator,'   ',ci(c$estimate,c$lower,c$upper)))
}
row_sel <- function(k,label){
 c=sel$contrasts[[k]]
 stopifnot(!is.null(c$difference))
 list(label=label,estimate=100*c$difference,lower=100*c$bootstrap_lower,upper=100*c$bootstrap_upper,
  text=paste0(c$one_events,'/',c$one_n,' vs ',c$two_events,'/',c$two_n,'   ',ci(c$difference,c$bootstrap_lower,c$bootstrap_upper)))
}
row_model <- function(m,label){
 stopifnot(!is.null(m$standardized_difference))
 list(label=label,estimate=100*m$standardized_difference,lower=100*m$bootstrap$lower,upper=100*m$bootstrap$upper,
  text=paste0(pct(m$standardized_one_pad),' vs ',pct(m$standardized_two_or_more),'   ',ci(m$standardized_difference,m$bootstrap$lower,m$bootstrap$upper)))
}
row_bound <- function(b,label){
 list(label=label,estimate=100*b$difference,lower=100*b$bootstrap_lower,upper=100*b$bootstrap_upper,
  text=paste0(b$one_events,'/',b$one_n,' vs ',b$two_events,'/',b$two_n,'   ',ci(b$difference,b$bootstrap_lower,b$bootstrap_upper)))
}
row_avail <- function(a,label){
 list(label=label,estimate=100*a$weighted_difference,lower=100*a$bootstrap_lower,upper=100*a$bootstrap_upper,
  text=paste0(pct(a$weighted_one_pad),' vs ',pct(a$weighted_two_or_more),'   ',ci(a$weighted_difference,a$bootstrap_lower,a$bootstrap_upper)))
}
row_ipw <- function(m,label){
 stopifnot(!is.null(m$weighted_difference))
 list(label=label,estimate=100*m$weighted_difference,lower=100*m$bootstrap$lower,upper=100*m$bootstrap$upper,
  text=paste0(pct(m$weighted_one_pad),' vs ',pct(m$weighted_two_or_more),'   ',ci(m$weighted_difference,m$bootstrap$lower,m$bootstrap$upper)))
}
sections=list(
 list(head='Assessment selection',rows=list(
  row_obs('P0','Reference rule'),
  row_obs('P1','Conflicting windows excluded'),
  row_obs('P2','First usable assessment'),
  row_obs('P3','Narrower assessment windows'),
  row_obs('P4','Uncertain assessment dates excluded'))),
 list(head='Pad-count measurement (post hoc)',rows=list(
  row_sel('exact_count_records','Exact counts only'),
  row_sel('epic_instrument_excluded','EPIC questionnaire counts excluded'),
  row_bound(st$unclassified_bounds$all_assigned_one,'Unclassifiable counts as one pad'),
  row_bound(st$unclassified_bounds$all_assigned_two_or_more,'Unclassifiable counts as two or more'))),
 list(head='Follow-up and missing records (post hoc)',rows=list(
  row_sel('window_closed_before_common_extract','Window closed before extraction'),
  row_sel('operative_era_2017_2024','Operated 2017–2024'),
  row_bound(st$outcome_definitions$widened_one_year_window,'One-year window extended to day 545'),
  row_avail(st$record_availability,'Weighted for record availability'))),
 list(head='Adjustment (post hoc)',rows=list(
  row_model(sel$posthoc_country_model_without_year_day,'Age, country, three-month day'),
  row_model(ph$centre_adjusted_sensitivity$no_yearday,'Centre, period, age, three-month day'),
  row_model(clin$clinical$model,'Clinical covariates added'),
  row_ipw(clin$ipw_clinical,'Clinical covariates, weighted'),
  row_model(clin$clinical_no_interim_treatment$model,'Clinical, no interim RT or ADT')))
)
# Reference row must equal the reference contrast in the selection record.
stopifnot(abs(sections[[1]]$rows[[1]]$estimate-100*sel$contrasts$reference$difference)<1e-9)

heads=list();items=list();rules=c();last=NULL
for(si in seq_along(sections)){
 s=sections[[si]]
 if(!is.null(last)){rules=c(rules,last-0.62);hy=last-1.25} else hy=0
 heads[[si]]=list(y=hy,label=s$head)
 y=hy-0.85
 for(r in s$rows){r$y=y;items[[length(items)+1]]=r;last=y;y=y-1}
}
shift=1-last
for(i in seq_along(heads))heads[[i]]$y=heads[[i]]$y+shift
for(i in seq_along(items))items[[i]]$y=items[[i]]$y+shift
rules=rules+shift
ys=sapply(items,function(r)r$y)
top=heads[[1]]$y

pA=blank_panel('A  Difference in documented pad freedom at one year, one pad minus two or more pads',top+0.55)
pA=pA+scale_x_continuous(limits=c(-111,223),expand=c(0,0))
gridticks=seq(0,60,by=20)
pA=pA+annotate('segment',x=gridticks,xend=gridticks,y=min(ys)-.45,yend=max(ys)+.3,linewidth=.2,colour='#d7d7d7')
pA=pA+annotate('segment',x=0,xend=0,y=.5,yend=max(ys)+.35,linewidth=.3,linetype='dashed',colour='#8c8c8c')
for(ry in rules)pA=pA+annotate('ribbon',x=c(-109,215),ymin=ry-0.02,ymax=ry+0.02,fill='#8c8c8c',colour=NA)
for(h in heads)pA=pA+text_at(-109,h$y,h$label,face='bold',col='#555555')
pA=pA+text_at(108,top,'One vs two or more   Difference (95% CI)',face='bold')
for(r in items){
 pA=pA+text_at(-109,r$y,wrap(r$label))+
  annotate('segment',x=r$lower,xend=r$upper,y=r$y,yend=r$y,linewidth=ci_lwd,colour='#000000')+
  annotate('point',x=r$estimate,y=r$y,size=pt_size,shape=18,colour='#000000')+
  text_at(108,r$y,r$text)
}
pA=axis_at(pA,60,'Difference (percentage points)',20)

# Part B. The completed-population difference is linear in both assumed proportions,
# so every contour is a straight line across the unit square.
mo=sel$missing_outcome$window_closed_before_common_extract
g1=mo$groups$one;g2=mo$groups$two
N1=g1$early_users;e1=g1$events;u1=g1$unobserved;n1=g1$observed
N2=g2$early_users;e2=g2$events;u2=g2$unobserved;n2=g2$observed
Dq=function(q1,q2)(e1+u1*q1)/N1-(e2+u2*q2)/N2
stopifnot(abs(Dq(e1/n1,e2/n2)-mo$observed_difference)<1e-9,abs(Dq(0,1)-mo$lower_bound)<1e-9)
contour_ends=function(L){
 pts=list()
 for(x in c(0,1)){y=((L+(e2+u2*x)/N2)*N1-e1)/u1;if(y>=-1e-9&&y<=1+1e-9)pts[[length(pts)+1]]=c(x,min(1,max(0,y)))}
 for(y in c(0,1)){x=(((e1+u1*y)/N1-L)*N2-e2)/u2;if(x>=-1e-9&&x<=1+1e-9)pts[[length(pts)+1]]=c(min(1,max(0,x)),y)}
 if(!length(pts))return(NULL)
 m=unique(round(do.call(rbind,pts),9))
 if(nrow(m)<2)return(NULL)
 m=m[order(m[,1],m[,2]),,drop=FALSE]
 m[c(1,nrow(m)),,drop=FALSE]
}
zero=contour_ends(0)
poly=list()
for(cn in list(c(0,0),c(1,0),c(1,1),c(0,1)))if(Dq(cn[2],cn[1])<=0)poly[[length(poly)+1]]=cn
poly[[length(poly)+1]]=zero[1,];poly[[length(poly)+1]]=zero[2,]
pm=do.call(rbind,poly);pm=pm[order(atan2(pm[,2]-mean(pm[,2]),pm[,1]-mean(pm[,1]))),]
ox=100*e2/n2;oy=100*e1/n1
dt=mo$symmetric_shift_tipping_delta
tx=ox+100*dt;ty=oy-100*dt
stopifnot(abs(Dq(ty/100,tx/100))<1e-6)
bt=function(x,y,label,hjust=0,col='#222222',face='plain')annotate('text',x=x,y=y,label=label,size=small,family='Open Sans',hjust=hjust,colour=col,fontface=face,lineheight=1.0)
# Labels that sit over contour lines get a white backing so no line crosses the text.
bl=function(x,y,label,hjust=0,col='#222222',face='plain')suppressWarnings(annotate('label',x=x,y=y,label=label,size=small,family='Open Sans',hjust=hjust,colour=col,fontface=face,lineheight=1.0,fill='white',label.size=0,border.colour='white',label.padding=unit(0.6,'mm'),label.r=unit(0,'mm')))
pB=ggplot()+
 annotate('polygon',x=100*pm[,1],y=100*pm[,2],fill='#F6DDD0',colour=NA)+
 annotate('rect',xmin=0,xmax=100,ymin=0,ymax=100,fill=NA,colour='#5a5a5a',linewidth=.3)
for(L in c(-0.2,-0.1,0.1,0.2,0.3,0.4,0.5)){
 z=contour_ends(L);if(is.null(z))next
 pB=pB+annotate('segment',x=100*z[1,1],xend=100*z[2,1],y=100*z[1,2],yend=100*z[2,2],linewidth=.25,colour='#9a9a9a')
 hi=z[which.max(z[,2]+z[,1]),]
 lab=sub('^-','−',sprintf('%d',as.integer(round(100*L))))
 if(hi[2]>=1-1e-9)pB=pB+bt(100*hi[1],103.5,lab,hjust=.5,col='#555555') else pB=pB+bt(102,100*hi[2],lab,hjust=0,col='#555555')
}
pB=pB+annotate('segment',x=100*zero[1,1],xend=100*zero[2,1],y=100*zero[1,2],yend=100*zero[2,2],linewidth=.8,colour='#D55E00')+
 bt(102,100*zero[2,2],'0',hjust=0,col='#D55E00',face='bold')+
 annotate('segment',x=0,xend=100,y=0,yend=100,linewidth=.3,linetype='dotted',colour='#5a5a5a')+
 annotate('segment',x=ox,xend=tx,y=oy,yend=ty,linewidth=.35,linetype='dashed',colour='#555555')+
 annotate('point',x=ox,y=oy,shape=18,size=2.8,colour='#0072B2')+
 annotate('point',x=tx,y=ty,shape=21,size=2.2,fill='white',colour='#D55E00',stroke=.7)+
 bl(ox+3,oy+4.5,'Unobserved men resemble\nobserved men')+
 bl(tx+3,ty-5,'Tipping point')+
 bl(3,93,'One-pad group more often pad-free',col='#0072B2',face='bold')+
 bl(97,6,'Two-or-more group\nmore often pad-free',hjust=1,col='#B24A00',face='bold')+
 bt(50,109,'Difference, percentage points',hjust=.5,col='#555555')+
 scale_x_continuous(limits=c(-1,112),breaks=seq(0,100,25),expand=c(0,0))+
 scale_y_continuous(limits=c(-1,113),breaks=seq(0,100,25),expand=c(0,0))+
 coord_fixed(ratio=1,clip='off')+
 labs(title='B  Missing one-year outcomes, men whose one-year window had closed',
  x='Assumed pad freedom among unobserved two-or-more users (%)',
  y='Assumed pad freedom among\nunobserved one-pad users (%)')+
 theme_postcddp(base_size=8)+
 theme(panel.grid=element_blank(),panel.grid.major=element_blank(),axis.text=element_text(size=7,family='Open Sans',colour='#222222'),
  axis.title=element_text(size=7,face='bold',family='Open Sans'),plot.margin=margin(2,3,2,3,'mm'))
fig=wrap_plots(list(pA,pB),ncol=1,heights=c(128,92))
export_figure(fig,list(pA,pB),'Figure2',226)
