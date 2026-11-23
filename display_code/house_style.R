user_lib <- '/home/konrad/R/x86_64-pc-linux-gnu-library/4.6'
if (dir.exists(user_lib) && !(user_lib %in% .libPaths())) {
  .libPaths(c(user_lib, .libPaths()))
}

suppressPackageStartupMessages({
  library(ggplot2)
  library(ragg)
  library(jsonlite)
  library(systemfonts)
  library(svglite)
  library(digest)
})

font_dir <- '/home/konrad/.cache/R/renv/library/OmicSelector-c9f55c96/linux-ubuntu-noble/R-4.5/x86_64-pc-linux-gnu/rmarkdown/rmd/h/bootstrap/css/fonts'
if (!('Open Sans' %in% tryCatch(unique(systemfonts::system_fonts()$family), error = function(e) character()))) {
  if (file.exists(file.path(font_dir, 'OpenSans.ttf'))) {
    systemfonts::register_font(
      name = 'Open Sans',
      plain = file.path(font_dir, 'OpenSans.ttf'),
      bold = file.path(font_dir, 'OpenSansBold.ttf'),
      italic = file.path(font_dir, 'OpenSansItalic.ttf'),
      bolditalic = file.path(font_dir, 'OpenSansBoldItalic.ttf')
    )
  }
}
postcddp_font_family <- 'Open Sans'

theme_postcddp <- function(base_size = 8,
                           base_family = postcddp_font_family,
                           grid_col = '#d7d7d7') {
  theme_minimal(base_size = base_size, base_family = base_family) +
    theme(
      plot.title = element_text(face = 'bold', size = base_size + 1.5, color = '#1a1a1a'),
      plot.subtitle = element_text(size = base_size + 0.5, color = '#3b3b3b'),
      plot.caption = element_text(size = base_size - 1, color = '#5a5a5a'),
      axis.title = element_text(face = 'bold', size = base_size + 0.5, color = '#222222'),
      axis.text = element_text(size = base_size - 1, color = '#222222'),
      legend.title = element_text(face = 'bold', size = base_size),
      legend.text = element_text(size = base_size - 1),
      strip.text = element_text(face = 'bold', size = base_size),
      panel.grid.major = element_line(color = grid_col, linewidth = 0.4),
      panel.grid.minor = element_blank(),
      legend.position = 'bottom',
      legend.key.size = unit(0.8, 'lines'),
      legend.spacing.y = unit(1, 'pt'),
      panel.spacing = unit(3, 'pt'),
      plot.margin = margin(2, 2, 2, 2, 'mm'),
      plot.title.position = 'plot',
      text = element_text(lineheight = 0.95)
    )
}

`%||%` <- function(x, y) if (is.null(x)) y else x

range_or_null <- function(x) {
  x <- suppressWarnings(as.numeric(x))
  x <- x[is.finite(x)]
  if (!length(x)) return(NULL)
  unname(range(x))
}

panel_axis_range <- function(panel_params, axis) {
  direct <- panel_params[[paste0(axis, '.range')]] %||% panel_params[[paste0(axis, '_range')]]
  if (!is.null(direct)) return(unname(as.numeric(direct)))
  scale_obj <- panel_params[[axis]]
  if (is.list(scale_obj)) {
    rng <- scale_obj$continuous_range %||% scale_obj$range$range
    if (!is.null(rng)) return(unname(as.numeric(rng)))
  }
  NULL
}

emit_ggplot_geometry <- function(plot, stem, render_path,
                                 out_dir = 'figures/qc',
                                 intentional_crops = list()) {
  if (!file.exists(render_path)) stop('render_path does not exist: ', render_path)
  built <- ggplot_build(plot)
  panels <- lapply(seq_along(built$layout$panel_params), function(panel_i) {
    pp <- built$layout$panel_params[[panel_i]]
    panel_layers <- lapply(seq_along(built$data), function(layer_i) {
      df <- built$data[[layer_i]]
      if ('PANEL' %in% names(df)) {
        df <- df[df$PANEL == panel_i, , drop = FALSE]
      }
      layer <- list(
        layer = paste0(class(plot$layers[[layer_i]]$geom)[1], ':', layer_i),
        x = range_or_null(df$x),
        y = range_or_null(df$y),
        xmin = range_or_null(df$xmin),
        xmax = range_or_null(df$xmax),
        xend = range_or_null(df$xend),
        ymin = range_or_null(df$ymin),
        ymax = range_or_null(df$ymax),
        yend = range_or_null(df$yend),
        ymin_final = range_or_null(df$ymin_final),
        ymax_final = range_or_null(df$ymax_final)
      )
      layer[!vapply(layer, is.null, logical(1))]
    })
    list(
      panel = as.character(panel_i),
      xlim = panel_axis_range(pp, 'x'),
      ylim = panel_axis_range(pp, 'y'),
      layers = panel_layers,
      intentional_crops = intentional_crops
    )
  })
  geometry <- list(
    schema_version = 'figure-geometry-v1',
    figure = stem,
    render_sha256 = digest::digest(file = render_path, algo = 'sha256'),
    panels = panels
  )
  dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
  out_path <- file.path(out_dir, paste0(stem, '_geometry.json'))
  jsonlite::write_json(geometry, out_path, auto_unbox = TRUE, pretty = TRUE, null = 'null')
  assert_no_geometry_clip(geometry)
  invisible(geometry)
}

geometry_extent <- function(layer, axis) {
  keys <- if (axis == 'x') c('x', 'xmin', 'xmax', 'xend') else
    c('y', 'ymin', 'ymax', 'yend', 'ymin_final', 'ymax_final')
  vals <- unlist(layer[intersect(keys, names(layer))], use.names = FALSE)
  range_or_null(vals)
}

crop_declared <- function(crops, layer, axis) {
  if (!length(crops)) return(FALSE)
  layer_id <- layer$layer %||% ''
  any(vapply(crops, function(crop) {
    if (!is.list(crop)) return(FALSE)
    crop_axis <- crop$axis %||% crop$axes %||% ''
    crop_layer <- crop$layer %||% crop$layer_id %||% '*'
    axis %in% crop_axis && (identical(crop_layer, '*') || identical(crop_layer, layer_id))
  }, logical(1)))
}

assert_no_geometry_clip <- function(geometry, margin_mult = 1e-6) {
  problems <- character()
  for (panel in geometry$panels) {
    for (axis in c('x', 'y')) {
      lim <- panel[[paste0(axis, 'lim')]]
      if (is.null(lim) || length(lim) != 2) next
      tol <- max(abs(diff(as.numeric(lim))) * margin_mult, 1e-9)
      for (layer in panel$layers) {
        ext <- geometry_extent(layer, axis)
        if (is.null(ext) || crop_declared(panel$intentional_crops, layer, axis)) next
        if (ext[1] < lim[1] - tol || ext[2] > lim[2] + tol) {
          problems <- c(problems, sprintf(
            'panel %s layer %s axis %s extent [%g, %g] outside view [%g, %g]',
            panel$panel, layer$layer, axis, ext[1], ext[2], lim[1], lim[2]))
        }
      }
    }
  }
  if (length(problems)) stop(paste(problems, collapse = '\n'), call. = FALSE)
  invisible(TRUE)
}
