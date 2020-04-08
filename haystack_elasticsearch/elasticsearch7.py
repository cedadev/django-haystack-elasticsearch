# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from django.conf import settings
from haystack.backends import BaseEngine
from haystack.constants import DEFAULT_OPERATOR, DJANGO_CT
from haystack.exceptions import MissingDependency
from haystack.utils import get_identifier, get_model_ct

from haystack_elasticsearch.elasticsearch6 import Elasticsearch6SearchBackend, Elasticsearch6SearchQuery

try:
    import elasticsearch

    if not ((7, 0, 0) <= elasticsearch.__version__ < (8, 0, 0)):
        raise ImportError
    from elasticsearch.helpers import bulk, scan

except ImportError:
    raise MissingDependency("The 'elasticsearch7' backend requires the \
                            installation of 'elasticsearch>=7.0.0,<8.0.0'. \
                            Please refer to the documentation.")


class Elasticsearch7SearchBackend(Elasticsearch6SearchBackend):

    def clear(self, models=None, commit=True):
        """
        Clears the backend of all documents/objects for a collection of models.

        :param models: List or tuple of models to clear.
        :param commit: Not used.
        """
        if models is not None:
            assert isinstance(models, (list, tuple))

        try:
            if models is None:
                self.conn.indices.delete(index=self.index_name, ignore=404)
                self.setup_complete = False
                self.existing_mapping = {}
                self.content_field_name = None
            else:
                models_to_delete = []

                for model in models:
                    models_to_delete.append("%s:%s" % (DJANGO_CT, get_model_ct(model)))

                # Delete using scroll API
                query = {'query': {'query_string': {'query': " OR ".join(models_to_delete)}}}
                generator = scan(self.conn, query=query, index=self.index_name)
                actions = ({
                    '_op_type': 'delete',
                    '_id': doc['_id'],
                } for doc in generator)

                bulk(self.conn, actions=actions, index=self.index_name)
                self.conn.indices.refresh(index=self.index_name)

        except elasticsearch.TransportError as e:
            if not self.silently_fail:
                raise

            if models is not None:
                self.log.error("Failed to clear Elasticsearch index of models '%s': %s",
                               ','.join(models_to_delete), e, exc_info=True)
            else:
                self.log.error("Failed to clear Elasticsearch index: %s", e, exc_info=True)

    def more_like_this(self, model_instance, additional_query_string=None,
                       start_offset=0, end_offset=None, models=None,
                       limit_to_registered_models=None, result_class=None, **kwargs):

        from haystack import connections

        if not self.setup_complete:
            self.setup()

        # Deferred models will have a different class ("RealClass_Deferred_fieldname")
        # which won't be in our registry:
        model_klass = model_instance._meta.concrete_model

        index = connections[self.connection_alias].get_unified_index().get_index(model_klass)
        field_name = index.get_content_field()
        params = {}

        if start_offset is not None:
            params['from_'] = start_offset

        if end_offset is not None:
            params['size'] = end_offset - start_offset

        doc_id = get_identifier(model_instance)

        try:
            # More like this Query
            # https://www.elastic.co/guide/en/elasticsearch/reference/2.2/query-dsl-mlt-query.html
            mlt_query = {
                'query': {
                    'more_like_this': {
                        'fields': [field_name],
                        'like': [{
                            "_id": doc_id
                        }]
                    }
                }
            }

            narrow_queries = []

            if additional_query_string and additional_query_string != '*:*':
                additional_filter = {
                    "query_string": {
                        "query": additional_query_string
                    }
                }
                narrow_queries.append(additional_filter)

            if limit_to_registered_models is None:
                limit_to_registered_models = getattr(settings, 'HAYSTACK_LIMIT_TO_REGISTERED_MODELS', True)

            if models and len(models):
                model_choices = sorted(get_model_ct(model) for model in models)

            elif limit_to_registered_models:
                # Using narrow queries, limit the results to only models handled
                # with the current routers.
                model_choices = self.build_models_list()

            else:
                model_choices = []

            if len(model_choices) > 0:
                model_filter = {"terms": {DJANGO_CT: model_choices}}
                narrow_queries.append(model_filter)

            if len(narrow_queries) > 0:
                mlt_query = {
                    "query": {
                        "bool": {
                            'must': mlt_query['query'],
                            'filter': {
                                'bool': {
                                    'must': list(narrow_queries)
                                }
                            }
                        }
                    }
                }

            raw_results = self.conn.search(
                body=mlt_query,
                index=self.index_name,
                _source=True, **params)
            
        except elasticsearch.TransportError as e:
            if not self.silently_fail:
                raise

            self.log.error("Failed to fetch More Like This from Elasticsearch for document '%s': %s",
                           doc_id, e, exc_info=True)
            raw_results = {}

        return self._process_results(raw_results, result_class=result_class)


class Elasticsearch7SearchQuery(Elasticsearch6SearchQuery):


class Elasticsearch7SearchEngine(BaseEngine):
    backend = Elasticsearch7SearchBackend
    query = Elasticsearch7SearchQuery
