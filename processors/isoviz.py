"""
Generate multiple area graphs and project them isometrically
"""
import csv
import re

from backend.abstract.processor import BasicProcessor
from backend.lib.helpers import UserInput

from calendar import monthrange, month_abbr
from math import sin, cos, tan, degrees, radians, copysign

from svgwrite import Drawing
from svgwrite.container import SVG
from svgwrite.shapes import Line, Rect
from svgwrite.path import Path
from svgwrite.text import Text


class IsometricMultigraphRenderer(BasicProcessor):
	"""
	Generate multiple area graphs, and project them on an isometric plane

	Allows for easy side-by-side comparison of prevalence of multiple
	attributes in a data set over time.
	"""
	type = "render-graphs-isometric"  # job type ID
	category = "Visual"  # category
	title = "Side-by-side graphs"  # title displayed in UI
	description = "Generate area graphs showing prevalence per item over time and project these side-by-side on an isometric plane for easy comparison."  # description displayed in UI
	extension = "svg"  # extension of result file, used internally and in UI

	accepts = ["vector-ranker", "preset-neologisms", "tfidf", "collocations", "attribute-frequencies"]
	options = {
		"smooth": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Smooth curves"
		},
		"normalise": {
			"type": UserInput.OPTION_TOGGLE,
			"default": True,
			"help": "Normalise values to 0-100% for each graph"
		}
	}

	# a palette generated with https://medialab.github.io/iwanthue/
	colours = ["#eb010a", "#495dff", "#f35f00", "#5137e0", "#ffeb45", "#d05edf",
			   "#00cb3a", "#b200c7", "#d8fd5d", "#a058ff", "#b90fd4", "#6fb300",
			   "#ff40b5", "#9eff3b", "#022bc3"]
	colour_index = 0

	def process(self):
		graphs = {}
		intervals = []

		smooth = self.parameters.get("smooth", self.options["smooth"]["default"])
		normalise_values = self.parameters.get("normalise", self.options["normalise"]["default"])

		# first gather graph data: each distinct item gets its own graph and
		# for each graph we have a sequence of intervals, each interval with
		# its own value
		with self.source_file.open() as input:
			reader = csv.DictReader(input)

			item_key = "text" if "text" in reader.fieldnames else "item"
			date_key = "time" if "time" in reader.fieldnames else "date"
			value_key = "value" if "value" in reader.fieldnames else "frequency"

			for row in reader:
				if row[item_key] not in graphs:
					graphs[row[item_key]] = {}

				# make sure the months and days are zero-padded
				interval = row.get(date_key, "")
				interval = "-".join([str(bit).zfill(2 if len(bit) != 4 else 4) for bit in interval.split("-")])

				if interval not in intervals:
					intervals.append(interval)

				if interval not in graphs[row[item_key]]:
					graphs[row[item_key]][interval] = 0

				graphs[row[item_key]][interval] += float(row.get(value_key, 0))

		# first make sure we actually have something to render
		intervals = sorted(intervals)
		if not intervals:
			self.job.finish(0)
			return

		# there may be items that do not have values for all intervals
		# this will distort the graph, so the next step is to make sure all
		# graphs consist of the same continuous interval list

		if re.match(r"^[0-9]{4}$", intervals[0]):
			# years are quite straightforward
			first, last = min([int(i) for i in intervals]), max([int(i) for i in intervals])
			for graph in graphs:
				for year in range(first, last + 1):
					if str(year) not in graphs[graph]:
						graphs[graph][str(year)] = 0

		elif re.match(r"^[0-9]{4}-[0-9]{2}(-[0-9]{2})?", intervals[0]):
			# more granular intervals require the following monstrosity to
			# ensure all intervals are available for every single graph
			has_day = re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", intervals[0])

			first_year, last_year = min([int(i[0:4]) for i in intervals]), max([int(i[0:4]) for i in intervals])
			first_month = min([int(i[5:7]) for i in intervals if int(i[0:4]) == first_year])
			last_month = max([int(i[5:7]) for i in intervals if int(i[0:4]) == last_year])

			if has_day:
				first_day = min(
					[int(i[8:10]) for i in intervals if int(i[0:4]) == first_year and int(i[5:7]) == first_month])
				last_day = max(
					[int(i[8:10]) for i in intervals if int(i[0:4]) == last_year and int(i[5:7]) == last_month])

			for graph in graphs:
				for year in range(first_year, last_year + 1):
					start_month = first_month if year == first_year else 1
					end_month = last_month if year == last_year else 12

					for month in range(start_month, end_month + 1):
						key = str(year) + "-" + str(month).zfill(2)
						if not has_day:
							if key not in graphs[graph]:
								graphs[graph][key] = 0
						else:
							start_day = first_day if year == first_year and month == first_month else 1
							end_day = last_day if year == last_year and month == last_month else \
								monthrange(year, month)[1]

							for day in range(start_day, end_day + 1):
								day_key = key + "-" + str(day).zfill(2)
								if day_key not in graphs[graph]:
									graphs[graph][day_key] = 0

		# now that's done, make sure the graph datapoints are in order
		intervals = sorted(list(graphs[list(graphs)[0]].keys()))
		for graph in graphs:
			graphs[graph] = {interval: graphs[graph][interval] for interval in sorted(graphs[graph])}

		# determine max value per item, so we can normalize them later
		limits = {}
		max_limit = 0
		for graph in graphs:
			for interval in graphs[graph]:
				limits[graph] = max(limits.get(graph, 0), abs(graphs[graph][interval]))
				max_limit = max(max_limit, abs(graphs[graph][interval]))

		# how many vertical grid lines (and labels) are to be included at most
		# 12 is a sensible default because it allows one label per month for a full
		# year's data
		max_gridlines = 12

		# If True, label is put at the lower left bottom of the graph rather than
		# outside it. Automatically set to True if one of the labels is long, as
		# else the label would fall off the screen
		label_in_graph = max([len(item) for item in graphs]) > 30

		# determine how wide each interval should be
		# the graph has a minimum width - but the graph's width will be
		# extended if at this minimum width each item does not have the
		# minimum per-item width
		min_full_width = 600
		min_item_width = 1
		item_width = max(min_item_width, min_full_width / len(intervals))

		# determine how much space each graph should get
		# same trade-off as for the interval width
		min_full_height = 300
		min_item_height = 100
		item_height = max(min_item_height, min_full_height / len(graphs))

		# margin - this should be enough for the text labels to fit in
		margin = 100

		# this determines the "flatness" of the isometric projection and an be
		# tweaked for different looks - basically corresponds to how far the
		# camera is above the horizon
		plane_angle = 120

		# don't change these
		plane_obverse = radians((180 - plane_angle) / 2)
		plane_angle = radians(plane_angle)

		# okay, now determine the full graphic size with these dimensions projected
		# semi-isometrically. We can also use these values later for drawing for
		# drawing grid lines, et cetera. The axis widths and heights here are the
		# dimensions of the bounding box wrapping the isometrically projected axes.
		x_axis_length = (item_width * (len(intervals) - 1))
		y_axis_length = (item_height * len(graphs))

		x_axis_width = (sin(plane_angle / 2) * x_axis_length)
		y_axis_width = (sin(plane_angle / 2) * y_axis_length)
		canvas_width = x_axis_width + y_axis_width

		x_axis_height = (cos(plane_angle / 2) * x_axis_length)
		y_axis_height = (cos(plane_angle / 2) * y_axis_length)
		canvas_height = x_axis_height + y_axis_height

		# now we have the dimensions, the canvas can be instantiated
		canvas = Drawing(str(self.dataset.get_results_path()),
						 size=(canvas_width + margin, canvas_height + (2 * margin)),
						 style="font-family:monospace")

		# draw gridlines - vertical
		gridline_x = y_axis_width
		gridline_y = margin + canvas_height

		step_x_horizontal = sin(plane_angle / 2) * item_width
		step_y_horizontal = cos(plane_angle / 2) * item_width
		step_x_vertical = sin(plane_angle / 2) * item_height
		step_y_vertical = cos(plane_angle / 2) * item_height

		# labels for x axis
		skip = max(1, int(len(intervals) / max_gridlines))
		for i in range(0, len(intervals)):
			if i % skip == 0:
				canvas.add(
					Line(start=(gridline_x, gridline_y), end=(gridline_x - y_axis_width, gridline_y - y_axis_height),
						 stroke="grey", stroke_width=0.25))

				# to properly position the rotated and skewed text a container
				# element is needed
				label1 = str(intervals[i])[0:4]
				center = (gridline_x, gridline_y)
				container = SVG(x=center[0] - 25, y=center[1], width="50", height="1.5em", overflow="visible")
				container.add(Text(
					insert=("25%", "100%"),
					text=label1,
					transform="rotate(%f) skewX(%f)" % (-degrees(plane_obverse), degrees(plane_obverse)),
					text_anchor="middle",
					baseline_shift="-0.75em",
					style="font-weight:bold;"
				))

				if re.match(r"^[0-9]{4}-[0-9]{2}", intervals[i]):
					label2 = month_abbr[int(str(intervals[i])[5:7])]
					if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", intervals[i]):
						label2 += " %i" % int(intervals[i][8:10])

					container.add(Text(
						insert=("25%", "100%"),
						text=label2,
						transform="rotate(%f) skewX(%f)" % (-degrees(plane_obverse), degrees(plane_obverse)),
						text_anchor="middle",
						baseline_shift="-1.75em"
					))

				canvas.add(container)

			gridline_x += step_x_horizontal
			gridline_y -= step_y_horizontal

		# draw graphs as filled beziers
		top = step_y_vertical * 1.5
		graph_start_x = y_axis_width
		graph_start_y = margin + canvas_height

		# draw graphs in reverse order, so the bottom one is most in the
		# foreground (in case of overlap)
		for graph in reversed(list(graphs)):
			self.dataset.update_status("Rendering graph for '%s'" % graph)

			# path starting at lower left corner of graph
			area_graph = Path(fill=self.colours[self.colour_index])
			area_graph.push("M %f %f" % (graph_start_x, graph_start_y))
			previous_value = None

			graph_x = graph_start_x
			graph_y = graph_start_y
			for interval in graphs[graph]:
				# normalise value
				value = graphs[graph][interval]
				try:
					limit = limits[graph] if normalise_values else max_limit
					value = top * copysign(abs(value) / limit, value)
				except ZeroDivisionError:
					value = 0

				if previous_value is None:
					# vertical line upwards to starting value of graph
					area_graph.push("L %f %f" % (graph_start_x, graph_start_y - value))
				elif not smooth:
					area_graph.push("L %f %f" % (graph_x, graph_y - value))
				else:
					# quadratic bezier from previous value to current value
					control_left = (
						graph_x - (step_x_horizontal / 2),
						graph_y + step_y_horizontal - previous_value - (step_y_horizontal / 2)
					)
					control_right = (
						graph_x - (step_x_horizontal / 2),
						graph_y - value + (step_y_horizontal / 2)
					)
					area_graph.push("C %f %f %f %f %f %f" % (*control_left, *control_right, graph_x, graph_y - value))

				previous_value = value
				graph_x += step_x_horizontal
				graph_y -= step_y_horizontal

			# line to the bottom of the graph at the current Y position
			area_graph.push("L %f %f" % (graph_x - step_x_horizontal, graph_y + step_y_horizontal))
			area_graph.push("Z")  # then close the Path
			canvas.add(area_graph)

			# add text labels - skewing is a bit complicated and we need a
			# "center" to translate the origins properly.
			if label_in_graph:
				insert = (
					graph_start_x + 5,
					graph_start_y - 10
				)
			else:
				insert = (
					graph_x - (step_x_horizontal) + 5,
					graph_y + step_y_horizontal - 10
				)

			# we need to take the skewing into account for the translation
			offset_y = tan(plane_obverse) * insert[0]
			canvas.add(Text(
				insert=(0, 0),
				text=graph,
				transform="skewY(%f) translate(%f %f)" % (
					-degrees(plane_obverse), insert[0], insert[1] + offset_y)
			))

			# cycle colours, back to the beginning if all have been used
			self.colour_index += 1
			if self.colour_index >= len(self.colours):
				self.colour_index = 0

			graph_start_x -= step_x_vertical
			graph_start_y -= step_y_vertical

		# draw gridlines - horizontal
		gridline_x = 0
		gridline_y = margin + canvas_height - y_axis_height
		for graph in graphs:
			gridline_x += step_x_vertical
			gridline_y += step_y_vertical
			canvas.add(Line(start=(gridline_x, gridline_y), end=(gridline_x + x_axis_width, gridline_y - x_axis_height),
							stroke="black", stroke_width=1))

		# x axis
		canvas.add(Line(
			start=(y_axis_width, margin + canvas_height),
			end=(canvas_width, margin + canvas_height - x_axis_height),
			stroke="black",
			stroke_width=2
		))

		# and finally save the SVG
		canvas.save(pretty=True)
		self.dataset.finish(len(graphs))