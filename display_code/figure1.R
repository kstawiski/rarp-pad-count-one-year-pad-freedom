source('scripts/plot_common.R')

# Panel A: 7-row patient flow diagram from completed-window records
pA <- blank_panel('A  Patient selection', 7.6, ymin = 0.4)
bh <- 0.36
left_x0 <- -109; left_x1 <- 16
right_x0 <- 26; right_x1 <- 178
xc <- (left_x0 + left_x1) / 2
flowbox <- function(x0, x1, y, fill = 'white') {
  annotate('rect', xmin = x0, xmax = x1, ymin = y - bh, ymax = y + bh, fill = fill, colour = '#1a1a1a', linewidth = 0.45)
}
for (i in seq_along(d$ladder)) {
  s <- d$ladder[[i]]
  y <- 8 - i
  fill <- if (isTRUE(s$shaded)) '#DCEAF5' else 'white'
  pA <- pA +
    flowbox(left_x0, left_x1, y, fill) +
    text_at(left_x0 + 3, y, s$label) +
    text_at(left_x1 - 3, y, s$count, hjust = 1, size = pt, face = 'bold')
  if (y > 1) {
    pA <- pA + annotate('segment', x = xc, xend = xc, y = y - bh - 0.02, yend = y - 1 + bh + 0.02, linewidth = 0.45, colour = '#1a1a1a',
                        arrow = grid::arrow(length = unit(1.0, 'mm'), type = 'closed'))
  }
  if (!is.null(s$side_label) && !is.null(s$side_count)) {
    pA <- pA +
      flowbox(right_x0, right_x1, y, 'white') +
      text_at(right_x0 + 3, y, s$side_label) +
      text_at(right_x1 - 3, y, s$side_count, hjust = 1, size = pt, face = 'bold') +
      annotate('segment', x = left_x1 + 0.4, xend = right_x0 - 0.4, y = y, yend = y, linewidth = 0.45, colour = '#1a1a1a',
               arrow = grid::arrow(length = unit(1.0, 'mm'), type = 'closed'))
  }
}

# Panel B: 100% horizontal stacked bars (one-year pad category by three-month pad count)
ys_b <- c(4.1, 3.1, 2.1, 1.1)
bh_b <- 0.28
pB <- blank_panel('B  Pad use at one year by daily pad count at three months', 6.05, xmin = -111, xmax = 180)
ticks_b <- unlist(d$axes$proportion_axis)
pB <- pB + annotate('segment', x = ticks_b, xend = ticks_b, y = min(ys_b) - 0.45, yend = max(ys_b) + 0.35, linewidth = 0.2, colour = '#d7d7d7')

# Clean 2x2 legend above bars
leg_items <- list(
  list(cat = 'pad_free', label = 'Pad-free', x = -109, y = 5.45),
  list(cat = 'one', label = 'Using pads, at most one per day', x = -35, y = 5.45),
  list(cat = 'two_or_more', label = 'More than one pad per day', x = -109, y = 4.92),
  list(cat = 'not_classifiable', label = 'Pads, count not recorded', x = -35, y = 4.92)
)
for (lg in leg_items) {
  border_col <- if (lg$cat == 'not_classifiable') '#7a7a7a' else NA
  pB <- pB +
    annotate('rect', xmin = lg$x, xmax = lg$x + 7, ymin = lg$y - 0.14, ymax = lg$y + 0.14,
             fill = bar_pal[[lg$cat]], colour = border_col, linewidth = 0.3) +
    text_at(lg$x + 10, lg$y, lg$label)
}

# Left row labels (no digits)
for (i in seq_along(d$panel_b)) {
  r <- d$panel_b[[i]]
  pB <- pB + text_at(-109, ys_b[i], r$label)
}

# Rectangles for stacked segments
for (i in seq_along(d$panel_b)) {
  r <- d$panel_b[[i]]
  y <- ys_b[i]
  for (seg in r$segments) {
    if (seg$xmax > seg$xmin) {
      bcol <- if (seg$category == 'not_classifiable') '#7a7a7a' else '#ffffff'
      blwd <- if (seg$category == 'not_classifiable') 0.35 else 0.3
      pB <- pB + annotate('rect', xmin = seg$xmin, xmax = seg$xmax, ymin = y - bh_b, ymax = y + bh_b,
                          fill = bar_pal[[seg$category]], colour = bcol, linewidth = blwd)
    }
  }
}

# Segment inside percentage labels (draw order matches B_segs)
for (i in seq_along(d$panel_b)) {
  r <- d$panel_b[[i]]
  y <- ys_b[i]
  for (seg in r$segments) {
    if (isTRUE(seg$show_label)) {
      tcol <- if (seg$category == 'pad_free') '#ffffff' else '#111111'
      pB <- pB + text_at((seg$xmin + seg$xmax) / 2, y, seg$inside_label, hjust = 0.5, col = tcol, face = 'bold')
    }
  }
}

# Right-hand n/N and pad-free % (95% CI) (draw order matches B_right)
for (i in seq_along(d$panel_b)) {
  r <- d$panel_b[[i]]
  pB <- pB + text_at(108, ys_b[i], r$right_text)
}

# Column header & x axis (matches B_header + B_axis)
Bheader <- paste0('Pad-free, n/N   % (', d$meta$confidence, '% CI)')
Cheader <- paste0('n/N   % (', d$meta$confidence, '% CI)')
pB <- pB + text_at(108, max(ys_b) + 0.55, Bheader, face = 'bold')
pB <- axis_at(pB, xmin = 0, xmax = 100, ticks = ticks_b, title = 'One-year pad status (%)')

# Panel C: Country-stratified pad freedom
Crows <- lapply(d$country, function(r) {
  r$label <- sub('^One pad per day', 'One pad', r$label)
  r$label <- sub('^Two or more pads per day', 'Two or more pads', r$label)
  r
})
pC <- forest_country(Crows, 'C  Documented pad freedom at one year within each country', header = Cheader, axis_title = 'Documented pad freedom at one year (%)')

# Panel D: Within-population differences (axis -20 to 60 because US lower limit is -2.5)
pD <- forest(
  d$contrasts,
  'D  Difference within each population, one pad minus two or more pads',
  c(3.4, 2.2, 1.2),
  contrast = TRUE,
  header = paste0('Percentage points (', d$meta$confidence, '% CI)'),
  axis_title = 'Difference (percentage points)',
  rule_at = 2.8,
  signed = TRUE
)

fig <- wrap_plots(list(pA, pB, pC, pD), ncol = 1, heights = c(64, 56, 62, 42), guides = 'collect', axis_titles = 'collect')
export_figure(fig, list(pA, pB, pC, pD), 'Figure1', 240, width = 180)
