source('scripts/plot_common.R')

# Panel A: Forest plot of sensitivity analyses (4 sections without "post hoc" text)
heads <- list()
items <- list()
rules <- c()
last <- NULL
for (si in seq_along(d$figure2_sections)) {
  s <- d$figure2_sections[[si]]
  if (!is.null(last)) {
    rules <- c(rules, last - 0.62)
    hy <- last - 1.25
  } else {
    hy <- 0
  }
  heads[[si]] <- list(y = hy, label = s$head)
  y <- hy - 0.85
  for (r in s$rows) {
    r$y <- y
    items[[length(items) + 1]] <- r
    last <- y
    y <- y - 1
  }
}
shift <- 1 - last
for (i in seq_along(heads)) heads[[i]]$y <- heads[[i]]$y + shift
for (i in seq_along(items)) items[[i]]$y <- items[[i]]$y + shift
rules <- rules + shift
ys <- sapply(items, function(r) r$y)
top <- heads[[1]]$y

pA <- blank_panel('A  Difference in documented pad freedom at one year, one pad minus two or more pads', top + 0.65, xmin = -130, xmax = 206, ymin = -1.30)
ticks_a <- unlist(d$axes$difference_axis)
pA <- pA +
  annotate('segment', x = ticks_a, xend = ticks_a, y = min(ys) - 0.45, yend = max(ys) + 0.3, linewidth = 0.2, colour = '#d7d7d7') +
  annotate('segment', x = 0, xend = 0, y = 0.5, yend = max(ys) + 0.35, linewidth = 0.3, linetype = 'dashed', colour = '#8c8c8c')
for (ry in rules) {
  pA <- pA + annotate('ribbon', x = c(-128, 199), ymin = ry - 0.02, ymax = ry + 0.02, fill = '#8c8c8c', colour = NA)
}
for (h in heads) {
  pA <- pA + text_at(-128, h$y, h$label, face = 'bold', col = '#555555')
}
pA <- pA + text_at(74, top, paste0('One vs two or more   Percentage points (', d$meta$confidence, '% CI)'), face = 'bold')
for (r in items) {
  pA <- pA +
    text_at(-128, r$y, wrap(r$label, width = 50)) +
    annotate('segment', x = r$lower, xend = r$upper, y = r$y, yend = r$y, linewidth = ci_lwd, colour = '#000000') +
    annotate('point', x = r$estimate, y = r$y, size = pt_size, shape = 18, colour = '#000000') +
    text_at(74, r$y, r$text)
}
tick_labels_a <- sub('^-', '−', as.character(ticks_a))
pA <- pA +
  annotate('segment', x = -10, xend = max(ticks_a), y = 0, yend = 0, linewidth = 0.25, colour = '#5a5a5a') +
  annotate('segment', x = ticks_a, xend = ticks_a, y = 0, yend = -0.10, linewidth = 0.25, colour = '#5a5a5a') +
  text_at(ticks_a, -0.36, tick_labels_a, hjust = 0.5) +
  text_at((-10 + max(ticks_a)) / 2, -0.98, 'Difference (percentage points)', hjust = 0.5, size = small, face = 'bold')

# Panel B: Missing one-year outcomes plane (189 one-pad and 137 two-or-more early users; 85 and 52 unobserved)
mo <- d$missing_outcome
N1 <- mo$one_early_users; e1 <- mo$one_events; u1 <- mo$one_unobserved; n1 <- mo$one_observed
N2 <- mo$two_early_users; e2 <- mo$two_events; u2 <- mo$two_unobserved; n2 <- mo$two_observed
Dq <- function(q1, q2) (e1 + u1 * q1) / N1 - (e2 + u2 * q2) / N2
stopifnot(abs(Dq(e1 / n1, e2 / n2) - mo$observed_difference) < 1e-9, abs(Dq(0, 1) - mo$lower_bound) < 1e-9)

contour_ends <- function(L) {
  pts <- list()
  for (x in c(0, 1)) {
    y <- ((L + (e2 + u2 * x) / N2) * N1 - e1) / u1
    if (y >= -1e-9 && y <= 1 + 1e-9) pts[[length(pts) + 1]] <- c(x, min(1, max(0, y)))
  }
  for (y in c(0, 1)) {
    x <- (((e1 + u1 * y) / N1 - L) * N2 - e2) / u2
    if (x >= -1e-9 && x <= 1 + 1e-9) pts[[length(pts) + 1]] <- c(min(1, max(0, x)), y)
  }
  if (!length(pts)) return(NULL)
  m <- unique(round(do.call(rbind, pts), 9))
  if (nrow(m) < 2) return(NULL)
  m <- m[order(m[, 1], m[, 2]), , drop = FALSE]
  m[c(1, nrow(m)), , drop = FALSE]
}

zero <- contour_ends(0)
poly <- list()
for (cn in list(c(0, 0), c(1, 0), c(1, 1), c(0, 1))) {
  if (Dq(cn[2], cn[1]) <= 0) poly[[length(poly) + 1]] <- cn
}
poly[[length(poly) + 1]] <- zero[1, ]
poly[[length(poly) + 1]] <- zero[2, ]
pm <- do.call(rbind, poly)
pm <- pm[order(atan2(pm[, 2] - mean(pm[, 2]), pm[, 1] - mean(pm[, 1]))), ]

ox <- 100 * e2 / n2
oy <- 100 * e1 / n1
dt <- mo$symmetric_shift_tipping_delta
tx <- ox + 100 * dt
ty <- oy - 100 * dt
stopifnot(abs(Dq(ty / 100, tx / 100)) < 1e-6)

bt <- function(x, y, label, hjust = 0, col = '#222222', face = 'plain') {
  annotate('text', x = x, y = y, label = label, size = small, family = 'Open Sans',
           hjust = hjust, colour = col, fontface = face, lineheight = 1.0)
}
bl <- function(x, y, label, hjust = 0, col = '#222222', face = 'plain') {
  suppressWarnings(annotate('label', x = x, y = y, label = label, size = small, family = 'Open Sans',
                            hjust = hjust, colour = col, fontface = face, lineheight = 1.0,
                            fill = 'white', label.size = 0, border.colour = 'white',
                            label.padding = unit(1.4, 'mm'), label.r = unit(0, 'mm')))
}

pB <- ggplot() +
  annotate('polygon', x = 100 * pm[, 1], y = 100 * pm[, 2], fill = '#F6DDD0', colour = NA) +
  annotate('rect', xmin = 0, xmax = 100, ymin = 0, ymax = 100, fill = NA, colour = '#5a5a5a', linewidth = 0.3)

for (Lp in unlist(d$axes$contour_levels_pct)) {
  L <- Lp / 100
  z <- contour_ends(L)
  if (is.null(z)) next
  is_zero <- Lp == 0
  pB <- pB + annotate(
    'segment',
    x = 100 * z[1, 1], xend = 100 * z[2, 1],
    y = 100 * z[1, 2], yend = 100 * z[2, 2],
    linewidth = if (is_zero) 0.8 else 0.25,
    colour = if (is_zero) '#D55E00' else '#9a9a9a'
  )
  hi <- z[which.max(z[, 2] + z[, 1]), ]
  lab <- sub('^-', '−', sprintf('%d', as.integer(Lp)))
  lcol <- if (is_zero) '#D55E00' else '#555555'
  lface <- if (is_zero) 'bold' else 'plain'
  if (hi[2] >= 1 - 1e-9) {
    pB <- pB + bt(100 * hi[1], 103.5, lab, hjust = 0.5, col = lcol, face = lface)
  } else {
    pB <- pB + bt(102, 100 * hi[2], lab, hjust = 0, col = lcol, face = lface)
  }
}

ticks_b <- unlist(d$axes$proportion_axis)
pB <- pB +
  annotate('segment', x = 0, xend = 100, y = 0, yend = 100, linewidth = 0.3, linetype = 'dotted', colour = '#5a5a5a') +
  annotate('text', x = 17.8, y = 25.8, label = 'Equal pad freedom in\nboth unobserved groups',
           size = small, family = 'Open Sans', colour = '#5a5a5a', angle = 45,
           hjust = 0.5, vjust = 0.5, lineheight = 0.95) +
  annotate('segment', x = ox, xend = tx, y = oy, yend = ty, linewidth = 0.35, linetype = 'dashed', colour = '#555555') +
  annotate('point', x = ox, y = oy, shape = 18, size = 2.8, colour = '#004488') +
  annotate('point', x = tx, y = ty, shape = 21, size = 2.2, fill = 'white', colour = '#D55E00', stroke = 0.7) +
  bl(ox + 3, oy + 4.5, 'Unobserved men resemble\nobserved men') +
  bl(tx + 3, ty - 5, 'Tipping point') +
  bl(3, 93, 'One-pad group more often pad-free', col = '#004488', face = 'bold') +
  bl(97, 6, 'Two-or-more group\nmore often pad-free', hjust = 1, col = '#B24A00', face = 'bold') +
  bt(50, 109.5, 'Difference, percentage points', hjust = 0.5, col = '#555555') +
  scale_x_continuous(limits = c(-1, 112), breaks = ticks_b, expand = c(0, 0)) +
  scale_y_continuous(limits = c(-1, 117), breaks = ticks_b, expand = c(0, 0)) +
  coord_fixed(ratio = 1, clip = 'off') +
  labs(
    title = 'B  Missing one-year outcomes',
    x = 'Assumed pad freedom among unobserved two-or-more users (%)',
    y = 'Assumed pad freedom among\nunobserved one-pad users (%)'
  ) +
  theme_postcddp(base_size = 8) +
  theme(
    panel.grid = element_blank(),
    panel.grid.major = element_blank(),
    axis.text = element_text(size = 7, family = 'Open Sans', colour = '#222222'),
    axis.title = element_text(size = 7, face = 'bold', family = 'Open Sans'),
    plot.margin = margin(2, 3, 2, 3, 'mm')
  )

fig <- wrap_plots(list(pA, pB), ncol = 1, heights = c(132, 96))
export_figure(fig, list(pA, pB), 'Figure2', 236, width = 180)
