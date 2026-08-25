"""Spectral demixing: split a two-channel localization list into
populations selected on the photon-count plot.

In spectral demixing, several dyes of similar wavelength are imaged on
two cameras. Plotting the photon counts as a 2D scatter shows distinct
populations corresponding to the dyes used.

This script expects a *single* localization file that already carries
both photon counts as two columns (``photons_ch0`` and ``photons_ch1``
by default).

Populations are selected on the 2D histogram of the two photon counts
by drawing a polygon around each one; localizations outside every
polygon are discarded. Both axes can be switched between linear and
logarithmic. See Figure 1c of Gimber, et al.

References
----------
Gimber N, Strauss S, Jungmann R, Schmoranzer J. Simultaneous multicolor
    DNA-PAINT without sequential fluid exchange using spectral demixing.
    Nano letters. 2022 Mar 15;22(7):2682.

Li Y, Shi W, Liu S, Cavka I, Wu YL, Matti U, Wu D, Koehler S, Ries J.
    Global fitting for high-accuracy multi-channel single-molecule
    localization. Nature Communications. 2022 Jun 6;13(1):3133.

:authors: Rafal Kowalewski
:copyright: Copyright (c) 2026 Jungmann Lab, MPI of Biochemistry
"""

from __future__ import annotations

import os.path
import re

import numpy as np
import pandas as pd
from PyQt6 import QtCore, QtGui, QtWidgets

# must come after the PyQt6 import so that matplotlib's qt_compat
# selects the PyQt6 binding (picasso core no longer imports PyQt6)
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg,
    NavigationToolbar2QT,
)
from matplotlib.colors import LogNorm
from matplotlib.patches import Polygon as PolygonPatch
from matplotlib.path import Path
from matplotlib.widgets import PolygonSelector

from picasso import io, lib, __version__

plt.style.use("ggplot")

#: Photon columns picked by default, in this order.
DEFAULT_COLUMNS = ("photons_ch0", "photons_ch1")

#: Colors cycled through when a new population is created.
COLORS = [
    "#e41a1c",
    "#377eb8",
    "#4daf4a",
    "#984ea3",
    "#ff7f00",
    "#a65628",
    "#f781bf",
    "#17becf",
]


class PolygonSelection:
    """A named polygon drawn around one population.

    The vertices are always in photon-count space, i.e. (photons of the
    first channel, photons of the second channel).

    Attributes
    ----------
    name : str
        Population name, used for the output file name.
    vertices : np.ndarray, shape (n, 2)
        Polygon vertices in photon-count space.
    color : str
        Matplotlib color used to draw the polygon.

    Parameters
    ----------
    name, vertices, color
        Values of the attributes above.
    """

    def __init__(
        self,
        name: str,
        vertices: np.ndarray,
        color: str,
    ) -> None:
        self.name = name
        self.vertices = vertices
        self.color = color


def assign_polygons(
    p1: np.ndarray,
    p2: np.ndarray,
    polygons: list[PolygonSelection],
) -> np.ndarray:
    """Assign localizations to the first polygon that contains them.

    Parameters
    ----------
    p1, p2 : np.ndarray
        Photon counts of the first and the second channel.
    polygons : list of PolygonSelection
        Polygons in drawing order; earlier polygons win where they
        overlap.

    Returns
    -------
    labels : np.ndarray, dtype int
        Polygon index per localization, -1 if inside none of them.
    """
    labels = np.full(len(p1), -1, dtype=np.int32)
    points = np.column_stack([p1, p2])
    finite = np.isfinite(points).all(axis=1)
    for i, polygon in enumerate(polygons):
        if len(polygon.vertices) < 3:
            continue
        inside = np.zeros(len(points), dtype=bool)
        inside[finite] = Path(polygon.vertices).contains_points(points[finite])
        labels[(labels == -1) & inside] = i
    return labels


def safe_name(name: str) -> str:
    """Return ``name`` reduced to characters safe in a file name."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("_")
    return cleaned or "population"


def axis_label(column: str) -> str:
    """Return an axis label for a photon column name."""
    return column if "photon" in column.lower() else f"photons {column}"


def find_photon_columns(locs: pd.DataFrame) -> list[str]:
    """Return the numeric columns that plausibly hold photon counts.

    ``DEFAULT_COLUMNS`` come first if present, then any other column
    whose name contains ``"photon"``, then the remaining numeric columns
    so that unusual namings can still be picked by hand.

    Parameters
    ----------
    locs : pd.DataFrame
        Localizations.

    Returns
    -------
    columns : list of str
        Candidate column names, best guesses first.
    """
    numeric = [
        c for c in locs.columns if pd.api.types.is_numeric_dtype(locs[c])
    ]
    preferred = [c for c in DEFAULT_COLUMNS if c in numeric]
    photons = [
        c for c in numeric if "photon" in c.lower() and c not in preferred
    ]
    rest = [c for c in numeric if c not in preferred and c not in photons]
    return preferred + photons + rest


class SpectralDemixWindow(QtWidgets.QMainWindow):
    """Main window: photon plots, population table and export.

    Attributes
    ----------
    locs : pd.DataFrame
        Localizations to be demixed.
    info : list of dict
        Metadata of ``locs``.
    path : str
        Path the localizations were loaded from; the output file names
        are derived from it.
    polygons : list of PolygonSelection
        The populations, each defined by a polygon in the photon-count
        plot.
    labels : np.ndarray
        Polygon index per localization, -1 for unassigned.

    Parameters
    ----------
    locs : pd.DataFrame
        Localizations to be demixed.
    info : list of dict
        Metadata of ``locs``.
    path : str
        Path the localizations were loaded from.
    parent : QtWidgets.QWidget, optional
        Parent widget.
    """

    def __init__(
        self,
        locs: pd.DataFrame,
        info: list[dict],
        path: str,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Spectral demixing - {os.path.basename(path)}")
        self.resize(1300, 850)
        self.locs = locs
        self.info = info
        self.path = path

        self.polygons: list[PolygonSelection] = []
        self.labels = np.full(len(locs), -1, dtype=np.int32)
        self.overlays: list = []
        self.axes = None
        self.polygon_selector = None
        self._updating_table = False

        self._setup_ui()
        self._on_columns_changed()

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QHBoxLayout(central)

        self.figure = plt.Figure()
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        plot_box = QtWidgets.QVBoxLayout()
        plot_box.addWidget(NavigationToolbar2QT(self.canvas, self))
        plot_box.addWidget(self.canvas)
        layout.addLayout(plot_box, stretch=3)
        layout.addLayout(self._build_side_panel(), stretch=1)

        self.statusBar().showMessage(
            f"{len(self.locs):,} localizations loaded".replace(",", " ")
        )

    def _build_side_panel(self) -> QtWidgets.QVBoxLayout:
        panel = QtWidgets.QVBoxLayout()

        data_box = QtWidgets.QGroupBox("Photon columns")
        data_grid = QtWidgets.QGridLayout(data_box)
        columns = find_photon_columns(self.locs)
        self.column1 = QtWidgets.QComboBox()
        self.column2 = QtWidgets.QComboBox()
        self.column1.addItems(columns)
        self.column2.addItems(columns)
        if len(columns) > 1:
            self.column2.setCurrentIndex(1)
        data_grid.addWidget(QtWidgets.QLabel("First channel:"), 0, 0)
        data_grid.addWidget(self.column1, 0, 1)
        data_grid.addWidget(QtWidgets.QLabel("Second channel:"), 1, 0)
        data_grid.addWidget(self.column2, 1, 1)
        panel.addWidget(data_box)

        plot_box = QtWidgets.QGroupBox("Plot")
        plot_grid = QtWidgets.QGridLayout(plot_box)
        self.xscale = QtWidgets.QComboBox()
        self.xscale.addItems(["log", "linear"])
        self.yscale = QtWidgets.QComboBox()
        self.yscale.addItems(["log", "linear"])
        self.bins = QtWidgets.QSpinBox()
        self.bins.setRange(20, 2000)
        self.bins.setValue(300)
        # only apply the new value on enter or focus loss, not on every
        # keystroke while a number is being typed
        self.bins.setKeyboardTracking(False)
        plot_grid.addWidget(QtWidgets.QLabel("x scale:"), 0, 0)
        plot_grid.addWidget(self.xscale, 0, 1)
        plot_grid.addWidget(QtWidgets.QLabel("y scale:"), 1, 0)
        plot_grid.addWidget(self.yscale, 1, 1)
        plot_grid.addWidget(QtWidgets.QLabel("Bins:"), 2, 0)
        plot_grid.addWidget(self.bins, 2, 1)
        panel.addWidget(plot_box)

        select_box = QtWidgets.QGroupBox("Populations")
        select_layout = QtWidgets.QVBoxLayout(select_box)
        self.hint = QtWidgets.QLabel(
            "Click to place polygon vertices, close it on the first "
            "vertex, then add it as a population. Hold shift to move the "
            "polygon, esc to start over."
        )
        self.hint.setWordWrap(True)
        select_layout.addWidget(self.hint)
        self.add_polygon_button = QtWidgets.QPushButton(
            "Add polygon as population"
        )
        self.add_polygon_button.clicked.connect(self._commit_polygon)
        select_layout.addWidget(self.add_polygon_button)
        panel.addWidget(select_box)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Selection", "Locs"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._on_table_edited)
        panel.addWidget(self.table, stretch=1)

        buttons = QtWidgets.QHBoxLayout()
        remove_button = QtWidgets.QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_selected)
        clear_button = QtWidgets.QPushButton("Clear all")
        clear_button.clicked.connect(self._clear)
        buttons.addWidget(remove_button)
        buttons.addWidget(clear_button)
        panel.addLayout(buttons)

        save_button = QtWidgets.QPushButton("Save populations...")
        save_button.clicked.connect(self.save)
        panel.addWidget(save_button)

        self.column1.currentIndexChanged.connect(self._on_columns_changed)
        self.column2.currentIndexChanged.connect(self._on_columns_changed)
        self.xscale.currentIndexChanged.connect(self.plot)
        self.yscale.currentIndexChanged.connect(self.plot)
        self.bins.valueChanged.connect(self.plot)
        return panel

    # ------------------------------------------------------------------
    # state
    # ------------------------------------------------------------------
    def _on_columns_changed(self) -> None:
        column1 = self.column1.currentText()
        column2 = self.column2.currentText()
        self.p1 = self.locs[column1].to_numpy(float)
        self.p2 = self.locs[column2].to_numpy(float)
        self.plot()

    # ------------------------------------------------------------------
    # plotting
    # ------------------------------------------------------------------
    def plot(self) -> None:
        """Redraw the photon histogram, the polygons and the table."""
        xlog = self.xscale.currentText() == "log"
        ylog = self.yscale.currentText() == "log"
        x, y = self.p1, self.p2
        valid = np.isfinite(x) & np.isfinite(y)
        if xlog:
            valid = valid & (x > 0)
        if ylog:
            valid = valid & (y > 0)

        self.figure.clear()
        self.overlays = []
        self.axes = self.figure.add_subplot(111)
        if valid.sum() > 1:
            self._draw_hist2d(x[valid], y[valid], xlog, ylog)
        self.axes.set_xscale("log" if xlog else "linear")
        self.axes.set_yscale("log" if ylog else "linear")
        self.axes.set_xlabel(axis_label(self.column1.currentText()))
        self.axes.set_ylabel(axis_label(self.column2.currentText()))
        self.axes.grid(False)
        self.axes.set_facecolor("white")

        self._setup_polygon_selector()
        self.refresh()

    def _draw_hist2d(
        self,
        x: np.ndarray,
        y: np.ndarray,
        xlog: bool,
        ylog: bool,
    ) -> None:
        """Draw the 2D photon histogram into ``self.axes``."""
        n_bins = self.bins.value()
        tx = np.log10(x) if xlog else x
        ty = np.log10(y) if ylog else y
        x_min, x_max = float(tx.min()), float(tx.max())
        y_min, y_max = float(ty.min()), float(ty.max())
        if x_max <= x_min or y_max <= y_min:
            return
        counts = lib.hist2d_numba(
            np.ascontiguousarray(tx),
            np.ascontiguousarray(ty),
            x_min,
            x_max,
            y_min,
            y_max,
            n_bins,
            n_bins,
        )
        edges_x = np.linspace(x_min, x_max, n_bins + 1)
        edges_y = np.linspace(y_min, y_max, n_bins + 1)
        if xlog:
            edges_x = 10**edges_x
        if ylog:
            edges_y = 10**edges_y
        image = self.axes.pcolormesh(
            edges_x,
            edges_y,
            np.ma.masked_equal(counts.T, 0),
            norm=LogNorm(),
            cmap="Greys",
            shading="flat",
        )
        self.figure.colorbar(image, ax=self.axes, label="localizations")
        self.axes.set_xlim(edges_x[0], edges_x[-1])
        self.axes.set_ylim(edges_y[0], edges_y[-1])

    def refresh(self) -> None:
        """Recompute the assignment, then redraw overlays and table."""
        self.labels = assign_polygons(self.p1, self.p2, self.polygons)
        self._draw_overlays()
        self._refresh_table()

    def _draw_overlays(self) -> None:
        """Draw the populations on top of the histogram."""
        for artist in self.overlays:
            artist.remove()
        self.overlays = []
        if self.axes is None:
            return
        self._draw_polygons()
        self.canvas.draw_idle()

    def _draw_polygons(self) -> None:
        for polygon in self.polygons:
            if len(polygon.vertices) < 3:
                continue
            patch = PolygonPatch(
                polygon.vertices,
                closed=True,
                facecolor=polygon.color,
                edgecolor=polygon.color,
                alpha=0.25,
                lw=1.5,
            )
            self.axes.add_patch(patch)
            self.overlays.append(patch)
            text = self.axes.annotate(
                polygon.name,
                polygon.vertices.mean(axis=0),
                color=polygon.color,
                ha="center",
                va="center",
                fontsize=9,
                fontweight="bold",
            )
            self.overlays.append(text)

    # ------------------------------------------------------------------
    # polygons
    # ------------------------------------------------------------------
    def _setup_polygon_selector(self) -> None:
        self.polygon_selector = None
        if self.axes is None:
            return
        self.polygon_selector = PolygonSelector(
            self.axes,
            lambda vertices: None,
            useblit=True,
            props=dict(color="k", lw=1.5, alpha=0.8),
        )

    def _commit_polygon(self) -> None:
        """Turn the drawn polygon into a named population."""
        selector = self.polygon_selector
        vertices = np.array(selector.verts) if selector is not None else []
        if len(vertices) < 3:
            QtWidgets.QMessageBox.information(
                self,
                "No polygon",
                "Draw a closed polygon with at least three vertices first.",
            )
            return
        name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Population name",
            "Name:",
            text=f"Species {len(self.polygons) + 1}",
        )
        if not ok or not name:
            return
        self.polygons.append(
            PolygonSelection(
                name=name,
                vertices=vertices,
                color=COLORS[len(self.polygons) % len(COLORS)],
            )
        )
        self.plot()

    # ------------------------------------------------------------------
    # table
    # ------------------------------------------------------------------
    def _refresh_table(self) -> None:
        self._updating_table = True
        self.table.setRowCount(len(self.polygons))
        for i, polygon in enumerate(self.polygons):
            count = int((self.labels == i).sum())
            name_item = QtWidgets.QTableWidgetItem(polygon.name)
            name_item.setForeground(QtGui.QBrush(QtGui.QColor(polygon.color)))
            description_item = QtWidgets.QTableWidgetItem(
                f"{len(polygon.vertices)} vertices"
            )
            count_item = QtWidgets.QTableWidgetItem(
                f"{count:,}".replace(",", " ")
            )
            read_only = ~QtCore.Qt.ItemFlag.ItemIsEditable
            for item in (description_item, count_item):
                item.setFlags(item.flags() & read_only)
            self.table.setItem(i, 0, name_item)
            self.table.setItem(i, 1, description_item)
            self.table.setItem(i, 2, count_item)
        self.table.resizeColumnsToContents()
        self._updating_table = False
        assigned = int((self.labels >= 0).sum())
        self.statusBar().showMessage(
            f"{assigned:,} of {len(self.locs):,} localizations "
            f"assigned to {len(self.polygons)} population(s)".replace(",", " ")
        )

    def _on_table_edited(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._updating_table or item.column() != 0:
            return
        if item.row() < len(self.polygons):
            self.polygons[item.row()].name = item.text()
            self._draw_overlays()

    def _remove_selected(self) -> None:
        rows = sorted(
            {index.row() for index in self.table.selectedIndexes()},
            reverse=True,
        )
        if not rows:
            return
        for row in rows:
            del self.polygons[row]
        for i, polygon in enumerate(self.polygons):
            polygon.color = COLORS[i % len(COLORS)]
        self.plot()

    def _clear(self) -> None:
        self.polygons = []
        self.plot()

    # ------------------------------------------------------------------
    # saving
    # ------------------------------------------------------------------
    def _selection_info(self, index: int) -> dict:
        """Return the metadata describing one population's polygon."""
        column1 = self.column1.currentText()
        column2 = self.column2.currentText()
        polygon = self.polygons[index]
        return {
            "Generated by": f"Picasso Spectral Demix : {__version__}",
            "Channel 1 column": column1,
            "Channel 2 column": column2,
            "Population": polygon.name,
            "Selection": "polygon",
            "Space": f"{column1} vs {column2}",
            "Vertices": [[float(v[0]), float(v[1])] for v in polygon.vertices],
        }

    def save(self) -> None:
        """Write one localization file per population."""
        if not self.polygons:
            return
        counts = [
            int((self.labels == i).sum()) for i in range(len(self.polygons))
        ]
        if not any(counts):
            QtWidgets.QMessageBox.information(
                self, "Nothing to save", "No localizations are selected."
            )
            return
        base = os.path.splitext(self.path)[0]
        directory = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Save populations to folder", os.path.dirname(self.path)
        )
        if not directory:
            return
        stem = os.path.basename(base)
        written = []
        for i, polygon in enumerate(self.polygons):
            if not counts[i]:
                continue
            out_path = os.path.join(
                directory, f"{stem}_{safe_name(polygon.name)}.hdf5"
            )
            info = self.info + [self._selection_info(i)]
            io.save_locs(out_path, self.locs[self.labels == i], info)
            written.append(f"{os.path.basename(out_path)}: {counts[i]} locs")
        QtWidgets.QMessageBox.information(
            self, "Saved", "\n".join(written) or "Nothing was written."
        )


def show_locs(
    locs: pd.DataFrame,
    info: list[dict],
    path: str,
    parent: QtWidgets.QWidget | None = None,
) -> SpectralDemixWindow | None:
    """Open the demixing window on already loaded localizations.

    Parameters
    ----------
    locs : pd.DataFrame
        Localizations carrying two photon columns.
    info : list of dict
        Metadata of ``locs``.
    path : str
        Path the localizations came from; output names derive from it.
    parent : QtWidgets.QWidget, optional
        Parent widget.

    Returns
    -------
    window : SpectralDemixWindow or None
        The opened window, or None if there are fewer than two numeric
        columns to plot.
    """
    if len(find_photon_columns(locs)) < 2:
        QtWidgets.QMessageBox.warning(
            parent,
            "Spectral demixing",
            "This file needs two numeric photon columns (one per spectral "
            "channel), for example photons_ch0 and photons_ch1.",
        )
        return None
    window = SpectralDemixWindow(locs, info, path, parent=parent)
    window.show()
    return window


class Plugin:
    """Adds a spectral demixing entry to the Picasso: Render menu."""

    def __init__(self, window) -> None:
        self.name = "render"
        self.window = window

    def execute(self) -> None:
        """Called when Picasso: Render starts."""
        action = self.window.plugin_menu.addAction("Spectral demixing...")
        action.triggered.connect(self.open_spectral_demixing)

    def open_spectral_demixing(self) -> None:
        """Called when the menu entry is clicked."""
        view = self.window.view
        if not view.locs_paths:
            QtWidgets.QMessageBox.information(
                self.window,
                "Spectral demixing",
                "Load localizations into Render first.",
            )
            return
        channel = view.get_channel("Choose a channel to demix")
        if channel is None:  # the channel dialog was cancelled
            return
        self.window_demix = show_locs(
            view.locs[channel],
            view.infos[channel],
            view.locs_paths[channel],
            parent=self.window,
        )
