source('scripts/plot_common.R')

XLIM <- c(-170, 850)
schem_panel <- function(title, ymax) {
  ggplot() +
    scale_x_continuous(limits = XLIM, expand = c(0, 0)) +
    scale_y_continuous(limits = c(-1.1, ymax), expand = c(0, 0)) +
    coord_cartesian(clip = 'off') +
    labs(title = title, x = NULL, y = NULL) +
    theme_postcddp(base_size = 8) +
    theme(
      axis.text = element_blank(),
      axis.title = element_blank(),
      axis.ticks = element_blank(),
      panel.grid = element_blank(),
      panel.grid.major = element_blank(),
      panel.grid.minor = element_blank(),
      legend.position = 'none',
      plot.margin = margin(2, 3, 2, 3, 'mm')
    )
}
bandrect <- function(x0, x1, y, fill) annotate('rect', xmin = x0, xmax = x1, ymin = y - 0.28, ymax = y + 0.28, fill = fill, colour = NA)
targetpt <- function(day, y, co) annotate('point', x = day, y = y, size = 2.2, shape = 18, colour = co)

e0 <- as.numeric(d$meta$early_0); e1 <- as.numeric(d$meta$early_1); et <- as.numeric(d$meta$early_target)
y0 <- as.numeric(d$meta$year_0); y1 <- as.numeric(d$meta$year_1); yt <- as.numeric(d$meta$year_target)
s0 <- as.numeric(d$meta$six_0); s1 <- as.numeric(d$meta$six_1); st <- as.numeric(d$meta$six_target)
t0 <- as.numeric(d$meta$two_year_0); t1 <- as.numeric(d$meta$two_year_1); tt <- as.numeric(d$meta$two_year_target)
ax_ticks <- unlist(d$axes$axis_s1_days)
nonzero_ticks <- ax_ticks[ax_ticks != 0]

pT <- schem_panel('Assessment windows after surgery (schematic, not data)', 6.9)
pT <- pT +
  bandrect(e0, e1, 5.2, '#DCEAF5') + targetpt(et, 5.2, '#004488') +
  text_at(et, 5.82, paste0('Nearest day ', et), hjust = 0.5, size = small, face = 'bold', col = '#004488') +
  text_at(-160, 5.2, 'About three months\n(main analysis)', size = small, face = 'bold') +
  bandrect(y0, y1, 3.8, '#DCEAF5') + targetpt(yt, 3.8, '#004488') +
  text_at(yt, 4.42, paste0('Nearest day ', yt), hjust = 0.5, size = small, face = 'bold', col = '#004488') +
  text_at(-160, 3.8, 'About one year\n(main analysis)', size = small, face = 'bold') +
  bandrect(s0, s1, 2.4, '#EDEDED') + targetpt(st, 2.4, '#8C8C8C') +
  text_at(st, 3.02, paste0('Nearest day ', st), hjust = 0.5, size = small, face = 'bold', col = '#666666') +
  text_at(-160, 2.4, 'Six months\n(supplementary)', size = small) +
  bandrect(t0, t1, 1.0, '#EDEDED') + targetpt(tt, 1.0, '#8C8C8C') +
  text_at(tt, 1.62, paste0('Nearest day ', tt), hjust = 0.5, size = small, face = 'bold', col = '#666666') +
  text_at(-160, 1.0, 'Two years\n(supplementary)', size = small) +
  annotate('segment', x = 0, xend = max(ax_ticks), y = -0.25, yend = -0.25, linewidth = 0.25, colour = '#5a5a5a') +
  annotate('segment', x = ax_ticks, xend = ax_ticks, y = -0.25, yend = -0.35, linewidth = 0.25, colour = '#5a5a5a') +
  annotate('point', x = 0, y = -0.25, size = 2.0, shape = 16, colour = '#1a1a1a') +
  text_at(-12, -0.25, 'Surgery (day 0)', hjust = 1) +
  text_at(nonzero_ticks, -0.62, as.character(nonzero_ticks), hjust = 0.5) +
  text_at(400, -1.0, 'Postoperative day', hjust = 0.5, size = small, face = 'bold')

pR <- schem_panel('Pad-count groups and outcome (schematic)', 5.4)
rule_rows <- list(
  list('One pad: every record with a count shows exactly one ordinary pad', 16, '#004488'),
  list('Two or more: every record with a count shows at least two', 17, '#D55E00'),
  list('Unclear: counts missing, or a range spanning one and two pads', 15, '#8C8C8C'),
  list('Conflicting: incompatible or invalid records', 15, '#8C8C8C'),
  list('One-year outcome: explicit record of no pad use', 18, '#000000')
)
ys <- seq(4.4, 0.4, length.out = 5)
for (i in seq_along(rule_rows)) {
  r <- rule_rows[[i]]
  pR <- pR +
    annotate('point', x = -140, y = ys[i], size = 2.0, shape = r[[2]], colour = r[[3]]) +
    text_at(-118, ys[i], r[[1]])
}
pR <- pR + text_at(-160, 5.1, 'The comparison uses the first two groups.', size = small, face = 'bold')

fig <- wrap_plots(list(pT, pR), ncol = 1, heights = c(72, 52), guides = 'collect', axis_titles = 'collect')
export_figure(fig, list(pT, pR), 'FigureS1', 112, width = 180)
