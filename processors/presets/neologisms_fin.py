"""
Extract neologisms
"""
from backend.lib.preset import ProcessorPreset

from common.lib.helpers import UserInput


class NeologismExtractor(ProcessorPreset):
	"""
	Run processor pipeline to extract neologisms
	"""
	type = "preset-neologisms-fin"  # job type ID
	category = "Combined processors"  # category. 'Combined processors' are always listed first in the UI.
	title = "Extract neologisms in Finnish"  # title displayed in UI
	description = "Retrieve uncommon terms by deleting all known words. Assumes Finnish-language data. " \
				  "Uses stopwords-iso as its stopword filter."
	extension = "csv"

	references = ["Van Soest, Jeroen. 2019. 'Language Innovation Tracker: Detecting language innovation in online discussion fora.' (MA thesis), Beuls, K. (Promotor), Van Eecke, P. (Advisor).'"]

	@staticmethod
	def is_compatible_with(module=None, user=None):
		"""
        Determine compatibility

        This preset is compatible with any dataset that has columns

        :param Dataset module:  Module ID to determine compatibility with
        :return bool:
        """
		return module.is_top_dataset() and module.get_extension() in ("csv", "ndjson") and module.language == 'fi'

	@classmethod
	def get_options(cls, parent_dataset=None, user=None):
		"""
		Get processor options
		"""
		options = {
			"timeframe": {
				"type": UserInput.OPTION_CHOICE,
				"default": "month",
				"options": {"all": "Overall", "year": "Year", "month": "Month", "week": "Week", "day": "Day"},
				"help": "Extract neologisms per"
			},
			"columns": {
				"type": UserInput.OPTION_TEXT,
				"help": "Column(s) from which to extract neologisms",
				"tooltip": "Each enabled column will be treated as a separate item to tokenise. Columns must contain text."
			},
		}
		if parent_dataset and parent_dataset.get_columns():
			columns = parent_dataset.get_columns()
			options["columns"]["type"] = UserInput.OPTION_MULTI
			options["columns"]["inline"] = True
			options["columns"]["options"] = {v: v for v in columns}
			default_options = [default for default in ["body", "text", "subject"] if default in columns]
			if default_options:
				options["columns"]["default"] = default_options.pop(0)

		return options

	def get_processor_pipeline(self):
		"""
		This queues a series of post-processors to extract neologisms from a
		dataset through Van Soest (2019)'s protocol. The resulting top vector
		ranking is used as the result of this processor, once available.
		"""
		timeframe = self.parameters.get("timeframe")
		columns = self.parameters.get("columns")

		pipeline = [
			# first, tokenise the posts, excluding all common words
			{
				"type": "tokenise-posts",
				"parameters": {
					"language": "finnish",
					"stem": False,
					"strip_symbols": True,
					"lemmatise": False,
					"docs_per": timeframe,
					"columns": columns,
					"filter": ["finnish_wordlist_big", "stopwords-iso-fi"]
				}
			},
			# then, create vectors for those tokens
			{
				"type": "vectorise-tokens",
				"parameters": {}
			},
			# finally, the top vectors constitute the result of this preset
			{
				"type": "vector-ranker",
				"parameters": {
					"amount": True,
					"top": 15,
				}
			}
		]

		return pipeline