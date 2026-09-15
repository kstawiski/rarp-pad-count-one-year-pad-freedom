suppressPackageStartupMessages({library(ggplot2);library(patchwork);library(jsonlite);library(digest)})
# v4 adaptation: ragg/svglite/systemfonts unavailable in this environment.
# Devices use base grDevices cairo/pdf/svg output at identical physical size
# and resolution; geometry emitter unchanged. Open Sans verified via fc-list.
source('scripts/house_style.R')
theme_set(theme_postcddp(base_size=8))
d <- jsonlite::fromJSON('data/plot_data.json',simplifyVector=FALSE)
pal <- c(pad_free='#009E73',one='#0072B2',two_or_more='#D55E00',nonconflicting_quantity_uncertain='#8C8C8C',unresolved_quantity_evidence='#8C8C8C',overall='#000000')
# v4: vermillion #D55E00 replaces amber #E69F00 for stronger one-vs-two separation;
# blue/vermillion is an Okabe-Ito colorblind-safe pair (deuteranopia distance rechecked in v4 QA).
ci_lwd <- 0.7
pt_size <- 2.0
pt <- 8 / (72.27/25.4)
small <- 7 / (72.27/25.4)
wrap <- function(x,width=39) paste(strwrap(x,width=width),collapse='\n')
# Equal physical x transform across every full-width panel. The quantitative
# axis itself spans only its declared range. Outside space is annotation space.
blank_panel <- function(title,ymax,xmin=-111,xmax=180) {
 ggplot()+scale_x_continuous(limits=c(xmin,xmax),expand=c(0,0))+
 scale_y_continuous(limits=c(-0.9,ymax),expand=c(0,0))+
 coord_cartesian(clip='off')+labs(title=title,x=NULL,y=NULL)+
 theme_postcddp(base_size=8)+theme(axis.text=element_blank(),axis.title=element_blank(),axis.ticks=element_blank(),panel.grid=element_blank(),panel.grid.major=element_blank(),panel.grid.minor=element_blank(),legend.position='none',plot.margin=margin(2,3,2,3,'mm'))
}
text_at <- function(x,y,label,size=small,hjust=0,col='#222222',face='plain') {
 annotate('text',x=x,y=y,label=label,size=size,family='Open Sans',hjust=hjust,lineheight=1.05,colour=col,fontface=face)
}
axis_at <- function(p, xmax=100, title='Documented pad freedom at one year (%)',step=25) {
 ticks=unlist(if(xmax==100)d$axes$proportion_axis else d$axes$difference_axis)
 p + annotate('segment',x=0,xend=xmax,y=0,yend=0,linewidth=.25,colour='#5a5a5a')+
 annotate('segment',x=ticks,xend=ticks,y=0,yend=-.10,linewidth=.25,colour='#5a5a5a')+
 text_at(ticks,-.27,as.character(ticks),hjust=.5)+text_at(xmax/2,-.69,title,hjust=.5,size=small,face='bold')
}
forest <- function(rows,title,ys,contrast=FALSE,header=NULL,axis_title=NULL,rule_at=NULL) {
 p=blank_panel(title,max(ys)+.65)
 xmax=if(contrast)60 else 100
 gridticks=seq(0,xmax,by=if(contrast)20 else 25)
 p=p+annotate('segment',x=gridticks,xend=gridticks,y=min(ys)-.45,yend=max(ys)+.3,linewidth=.2,colour='#d7d7d7')
 if(contrast)p=p+annotate('segment',x=0,xend=0,y=.5,yend=max(ys)+.35,linewidth=.3,linetype='dashed',colour='#8c8c8c')
 # Optional thin rules (for example the Figure 1 part D separator between
 # the combined row and the country rows) are drawn as data-space ribbons
 # so the training range covers them. Zero-height segments at the panel
 # edge sit outside the training range and are silently dropped.
 if(!is.null(rule_at))for(ry in rule_at)p=p+annotate('ribbon',x=c(-109,175),ymin=ry-0.02,ymax=ry+0.02,fill='#8c8c8c',colour=NA)
 for(i in seq_along(rows)) {
  r=rows[[i]];y=ys[i];kind=r$kind %||% 'overall';co=pal[[kind]]
  shape=if(kind=='one')16 else if(kind=='two_or_more')17 else if(kind=='overall')18 else 15
  show=TRUE;if(!is.null(r$show_interval))show=isTRUE(r$show_interval)
  show_point=isTRUE(r$show_point %||% TRUE)
  p=p+text_at(-109,y,wrap(r$label))
  if(show)p=p+annotate('segment',x=as.numeric(r$lower),xend=as.numeric(r$upper),y=y,yend=y,linewidth=ci_lwd,colour=co)
  if(show_point)p=p+annotate('point',x=as.numeric(r$estimate),y=y,size=pt_size,shape=shape,colour=co)
  p=p+text_at(108,y,r$text)
 }
 if(!is.null(header))p=p+text_at(108,max(ys)+.56,header,face='bold')
 default_title=if(contrast)'One-minus-two-or-more difference (percentage points)' else 'Documented pad freedom at one year (%)'
 axis_at(p,xmax,if(!is.null(axis_title))axis_title else default_title,if(contrast)20 else 25)
}
# Figure 1 part B: ordered rows, a labelled grey documentation-state block,
# then the overall row, with a separator at each block boundary.
forest_block <- function(rows,title,ys,header=NULL,subhead_at=NULL,rule_at=NULL,subhead=NULL,axis_title='Documented pad freedom at one year (%)') {
 p=blank_panel(title,max(ys)+.65)
 xmax=100;gridticks=seq(0,100,by=25)
 # Grid lines stay inside the quantitative region so they cannot cross labels.
 p=p+annotate('segment',x=gridticks,xend=gridticks,y=min(ys)-.45,yend=max(ys)+.3,linewidth=.2,colour='#d7d7d7')
 for(i in seq_along(rows)) {
  r=rows[[i]];y=ys[i];kind=r$kind %||% 'overall';co=pal[[kind]]
  shape=if(kind=='one')16 else if(kind=='two_or_more')17 else if(kind=='overall')18 else 15
  show=TRUE;if(!is.null(r$show_interval))show=isTRUE(r$show_interval)
  show_point=isTRUE(r$show_point %||% TRUE)
  p=p+text_at(-109,y,wrap(r$label))
  if(show)p=p+annotate('segment',x=as.numeric(r$lower),xend=as.numeric(r$upper),y=y,yend=y,linewidth=ci_lwd,colour=co)
  if(show_point)p=p+annotate('point',x=as.numeric(r$estimate),y=y,size=pt_size,shape=shape,colour=co)
  p=p+text_at(108,y,r$text)
 }
 if(!is.null(rule_at))for(ry in rule_at)p=p+annotate('segment',x=-109,xend=175,y=ry,yend=ry,linewidth=.25,colour='#8c8c8c')
 if(!is.null(subhead))p=p+text_at(-109,subhead_at,subhead,face='bold',col='#555555')
 if(!is.null(header))p=p+text_at(108,max(ys)+.56,header,face='bold')
 axis_at(p,100,axis_title,25)
}
# Figure 1 part C: country subheadings above their rows. The quantitative
# grid stays inside the axis region. Six row positions grouped per country,
# each subheading about 0.65 above the first row of its block, with a thin
# separator between the blocks at the inter-block gap midpoint. Row order per
# country: Overall, one ordinary pad, two or more ordinary pads.
forest_country <- function(rows,title,header=NULL,axis_title='Documented pad freedom at one year (%)') {
 countries=unique(sub(' overall$','',sapply(rows,function(r)r$label)[seq(1,length(rows),by=3)]))
 ys=c(7.6,6.6,5.6,3.4,2.4,1.4);subheads=c(8.25,4.05);sep=4.5
 p=blank_panel(title,max(ys)+.65,xmax=180)
 xmax=100;gridticks=seq(0,100,by=25)
 p=p+annotate('segment',x=gridticks,xend=gridticks,y=min(ys)-.45,yend=max(ys)+.3,linewidth=.2,colour='#d7d7d7')
 p=p+annotate('segment',x=-109,xend=175,y=sep,yend=sep,linewidth=.25,colour='#8c8c8c')
 for(i in seq_along(rows)) {
  r=rows[[i]];y=ys[i];kind=r$kind %||% 'overall';co=pal[[kind]]
  shape=if(kind=='one')16 else if(kind=='two_or_more')17 else if(kind=='overall')18 else 15
  show=TRUE;if(!is.null(r$show_interval))show=isTRUE(r$show_interval)
  show_point=isTRUE(r$show_point %||% TRUE)
  lab=r$label;lab=sub('^(Poland|United States) overall$','Overall',lab);lab=sub(' in (Poland|United States)$','',lab)
  p=p+text_at(-109,y,wrap(lab))
  if(show)p=p+annotate('segment',x=as.numeric(r$lower),xend=as.numeric(r$upper),y=y,yend=y,linewidth=ci_lwd,colour=co)
  if(show_point)p=p+annotate('point',x=as.numeric(r$estimate),y=y,size=pt_size,shape=shape,colour=co)
  p=p+text_at(108,y,r$text)
 }
 for(j in seq_along(countries))p=p+text_at(-109,subheads[j],countries[j],face='bold',col='#111111')
 if(!is.null(header))p=p+text_at(108,max(ys)+.56,header,face='bold')
 axis_at(p,100,axis_title,25)
}
export_figure <- function(fig,panels,stem,height) {
 width=190
  ggsave(paste0('figures/',stem,'.pdf'),fig,width=width,height=height,units='mm',device=cairo_pdf,bg='white')
  status=system2('env',c('-u','LD_LIBRARY_PATH','/home/konrad/.venvs/konsta-research-py314/bin/python','-B','scripts/fix_pdf_canvas.py',paste0('figures/',stem,'.pdf'),width,height))
  if(status!=0)stop('PDF canvas correction failed')
  ggsave(paste0('figures/',stem,'.svg'),fig,width=width,height=height,units='mm',device=svg,bg='white')
  ggsave(paste0('figures/',stem,'.png'),fig,width=width,height=height,units='mm',dpi=600.5,type='cairo',device='png',bg='white')
  ggsave(paste0('figures/',stem,'.tiff'),fig,width=width,height=height,units='mm',dpi=1000.5,type='cairo',device='tiff',compression='lzw',bg='white')
 # The reference emitter builds individual ggplots. Enumerate every patchwork
 # child explicitly so geometry cannot silently describe only its final child.
 geoms=lapply(seq_along(panels),function(i) emit_ggplot_geometry(panels[[i]],paste0(stem,'_',LETTERS[i]),paste0('figures/',stem,'.png'),out_dir='figures/qc'))
 allpanels=list()
 for(i in seq_along(geoms))for(p in geoms[[i]]$panels){p$panel=paste0(LETTERS[i],'.',p$panel);allpanels[[length(allpanels)+1]]=p}
 geo=list(schema_version='figure-geometry-v1',figure=stem,render_sha256=digest(file=paste0('figures/',stem,'.png'),algo='sha256'),panels=allpanels)
 assert_no_geometry_clip(geo)
 write_json(geo,paste0('figures/',stem,'.geometry.json'),auto_unbox=TRUE,pretty=TRUE)
 message(stem,' rendered at ',width,' x ',height,' mm; PNG 600 dpi; TIFF 1000 dpi.')
}
