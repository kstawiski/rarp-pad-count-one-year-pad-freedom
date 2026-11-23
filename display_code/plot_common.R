source('scripts/house_style.R')
suppressPackageStartupMessages({
  library(patchwork)
})
theme_set(theme_postcddp(base_size = 8))
d <- jsonlite::fromJSON('data/plot_data.json', simplifyVector = FALSE)

# Unified Okabe-Ito-based palette for Figure 1 (min deuteranopia distance >= 36 across bar colors):
# Dark navy #004488 (L*=29.2), Sky blue #56B4E9 (L*=69.8), Vermillion #D55E00 (L*=54.2), Light grey #E5E5E5 (L*=90.9)
bar_pal <- c(
  pad_free = '#004488',
  one = '#56B4E9',
  two_or_more = '#D55E00',
  not_classifiable = '#E5E5E5'
)
pal <- c(
  pad_free = '#009E73',
  one = '#004488',
  two_or_more = '#D55E00',
  nonconflicting_quantity_uncertain = '#8C8C8C',
  unresolved_quantity_evidence = '#8C8C8C',
  overall = '#000000'
)

ci_lwd <- 0.7
pt_size <- 2.0
pt <- 8 / (72.27 / 25.4)
small <- 7 / (72.27 / 25.4)
wrap <- function(x, width = 36) paste(strwrap(x, width = width), collapse = '\n')

blank_panel <- function(title, ymax, xmin = -111, xmax = 180, ymin = -1.1) {
  ggplot() +
    scale_x_continuous(limits = c(xmin, xmax), expand = c(0, 0)) +
    scale_y_continuous(limits = c(ymin, ymax), expand = c(0, 0)) +
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

text_at <- function(x, y, label, size = small, hjust = 0, col = '#222222', face = 'plain') {
  annotate('text', x = x, y = y, label = label, size = size, family = 'Open Sans',
           hjust = hjust, lineheight = 1.02, colour = col, fontface = face)
}

axis_at <- function(p, xmin = 0, xmax = 100, ticks = c(0, 25, 50, 75, 100), title = 'Documented pad freedom at one year (%)') {
  tick_labels <- sub('^-', '−', as.character(ticks))
  p +
    annotate('segment', x = xmin, xend = xmax, y = 0, yend = 0, linewidth = 0.25, colour = '#5a5a5a') +
    annotate('segment', x = ticks, xend = ticks, y = 0, yend = -0.10, linewidth = 0.25, colour = '#5a5a5a') +
    text_at(ticks, -0.36, tick_labels, hjust = 0.5) +
    text_at((xmin + xmax) / 2, -0.82, title, hjust = 0.5, size = small, face = 'bold')
}

forest <- function(rows, title, ys, contrast = FALSE, header = NULL, axis_title = NULL, rule_at = NULL, signed = FALSE) {
  p <- blank_panel(title, max(ys) + 0.72)
  ticks <- unlist(if (contrast) (if (signed) d$axes$difference_axis_signed else d$axes$difference_axis) else d$axes$proportion_axis)
  xmin_ax <- min(ticks)
  xmax_ax <- max(ticks)
  p <- p + annotate('segment', x = ticks, xend = ticks, y = min(ys) - 0.45, yend = max(ys) + 0.3, linewidth = 0.2, colour = '#d7d7d7')
  if (contrast) p <- p + annotate('segment', x = 0, xend = 0, y = 0.5, yend = max(ys) + 0.35, linewidth = 0.3, linetype = 'dashed', colour = '#8c8c8c')
  if (!is.null(rule_at)) {
    for (ry in rule_at) p <- p + annotate('ribbon', x = c(-109, 178), ymin = ry - 0.02, ymax = ry + 0.02, fill = '#8c8c8c', colour = NA)
  }
  for (i in seq_along(rows)) {
    r <- rows[[i]]
    y <- ys[i]
    kind <- r$kind %||% 'overall'
    co <- pal[[kind]]
    shape <- if (kind == 'one') 16 else if (kind == 'two_or_more') 17 else if (kind == 'overall') 18 else 15
    show <- isTRUE(r$show_interval %||% TRUE)
    show_point <- isTRUE(r$show_point %||% TRUE)
    p <- p + text_at(-109, y, wrap(r$label, width = 30))
    if (show) p <- p + annotate('segment', x = as.numeric(r$lower), xend = as.numeric(r$upper), y = y, yend = y, linewidth = ci_lwd, colour = co)
    if (show_point) p <- p + annotate('point', x = as.numeric(r$estimate), y = y, size = pt_size, shape = shape, colour = co)
    p <- p + text_at(92, y, r$text)
  }
  if (!is.null(header)) p <- p + text_at(92, max(ys) + 0.58, header, face = 'bold')
  default_title <- if (contrast) 'One-minus-two-or-more difference (percentage points)' else 'Documented pad freedom at one year (%)'
  axis_at(p, xmin = xmin_ax, xmax = xmax_ax, ticks = ticks, title = if (!is.null(axis_title)) axis_title else default_title)
}

forest_country <- function(rows, title, header = NULL, axis_title = 'Documented pad freedom at one year (%)') {
  countries <- unique(sub(' overall$', '', sapply(rows, function(r) r$label)[seq(1, length(rows), by = 3)]))
  ys <- c(7.6, 6.6, 5.6, 3.4, 2.4, 1.4)
  subheads <- c(8.25, 4.05)
  sep <- 4.5
  p <- blank_panel(title, max(ys) + 0.72, xmax = 180)
  ticks <- unlist(d$axes$proportion_axis)
  p <- p + annotate('segment', x = ticks, xend = ticks, y = min(ys) - 0.45, yend = max(ys) + 0.3, linewidth = 0.2, colour = '#d7d7d7')
  p <- p + annotate('segment', x = -109, xend = 178, y = sep, yend = sep, linewidth = 0.25, colour = '#8c8c8c')
  for (i in seq_along(rows)) {
    r <- rows[[i]]
    y <- ys[i]
    kind <- r$kind %||% 'overall'
    co <- pal[[kind]]
    shape <- if (kind == 'one') 16 else if (kind == 'two_or_more') 17 else if (kind == 'overall') 18 else 15
    lab <- r$label
    lab <- sub('^(Poland|United States) overall$', 'Overall', lab)
    lab <- sub(' in (Poland|United States)$', '', lab)
    p <- p +
      text_at(-109, y, wrap(lab, width = 34)) +
      annotate('segment', x = as.numeric(r$lower), xend = as.numeric(r$upper), y = y, yend = y, linewidth = ci_lwd, colour = co) +
      annotate('point', x = as.numeric(r$estimate), y = y, size = pt_size, shape = shape, colour = co) +
      text_at(108, y, r$text)
  }
  for (j in seq_along(countries)) p <- p + text_at(-109, subheads[j], countries[j], face = 'bold', col = '#111111')
  if (!is.null(header)) p <- p + text_at(108, max(ys) + 0.58, header, face = 'bold')
  axis_at(p, xmin = 0, xmax = 100, ticks = ticks, title = axis_title)
}

export_figure <- function(fig, panels, stem, height, width = 180) {
  dir.create('figures', showWarnings = FALSE)
  pdf_path <- paste0('figures/', stem, '.pdf')
  svg_path <- paste0('figures/', stem, '.svg')
  png_path <- paste0('figures/', stem, '.png')
  tiff_path <- paste0('figures/', stem, '.tiff')

  ggsave(pdf_path, fig, width = width, height = height, units = 'mm', device = cairo_pdf, bg = 'white')
  status <- system2('env', c('-u', 'LD_LIBRARY_PATH', '/home/konrad/.venvs/konsta-research-py314/bin/python', '-B', 'scripts/fix_pdf_canvas.py', pdf_path, as.character(width), as.character(height)))
  if (status != 0) stop('PDF canvas correction failed')

  svglite::svglite(svg_path, width = width / 25.4, height = height / 25.4, bg = 'white', standalone = TRUE)
  print(fig)
  dev.off()

  ggsave(png_path, fig, width = width, height = height, units = 'mm', dpi = 300.5, device = ragg::agg_png, bg = 'white')

  ragg::agg_tiff(tiff_path, width = width, height = height, units = 'mm', res = 1200.2, compression = 'lzw', bitsize = 8, background = 'white')
  print(fig)
  dev.off()
  tiff_dpi <- 1200
  if (file.info(tiff_path)$size >= 60 * 1024 * 1024) {
    ragg::agg_tiff(tiff_path, width = width, height = height, units = 'mm', res = 600.2, compression = 'lzw', bitsize = 8, background = 'white')
    print(fig)
    dev.off()
    tiff_dpi <- 600
  }

  geoms <- lapply(seq_along(panels), function(i) emit_ggplot_geometry(panels[[i]], paste0(stem, '_', LETTERS[i]), png_path, out_dir = 'figures/qc'))
  allpanels <- list()
  for (i in seq_along(geoms)) {
    for (p in geoms[[i]]$panels) {
      p$panel <- paste0(LETTERS[i], '.', p$panel)
      allpanels[[length(allpanels) + 1]] <- p
    }
  }
  geo <- list(
    schema_version = 'figure-geometry-v1',
    figure = stem,
    width_mm = width,
    height_mm = height,
    tiff_dpi = tiff_dpi,
    tiff_bytes = file.info(tiff_path)$size,
    render_sha256 = digest::digest(file = png_path, algo = 'sha256'),
    panels = allpanels
  )
  assert_no_geometry_clip(geo)
  write_json(geo, paste0('figures/', stem, '.geometry.json'), auto_unbox = TRUE, pretty = TRUE)
  message(stem, ' rendered at ', width, ' x ', height, ' mm; PNG 300 dpi; TIFF ', tiff_dpi, ' dpi (', round(geo$tiff_bytes / 1048576, 2), ' MB).')
}
