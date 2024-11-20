# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from django.conf import settings
from haystack.backends import BaseEngine
from haystack.constants import DEFAULT_OPERATOR, DJANGO_CT, DJANGO_ID, ID
from haystack.exceptions import MissingDependency, SkipDocument
from haystack.utils import get_identifier, get_model_ct
import haystack
from elasticsearch.exceptions import NotFoundError
from haystack.backends import log_query
from haystack.models import SearchResult


from haystack_elasticsearch.elasticsearch6 import Elasticsearch6SearchBackend, Elasticsearch6SearchQuery

try:
    import elasticsearch

    if not ((8, 0, 0) <= elasticsearch.__version__ < (9, 0, 0)):
        raise ImportError
    from elasticsearch.helpers import bulk, scan

except ImportError:
    raise MissingDependency("The 'elasticsearch8' backend requires the \
                            installation of 'elasticsearch>=8.0.0,<9.0.0'. \
                            Please refer to the documentation.")


class Elasticsearch8SearchBackend(Elasticsearch6SearchBackend):

    def setup(self):
        """
        Defers loading until needed.
        """
        # Get the existing mapping & cache it. We'll compare it
        # during the ``update`` & if it doesn't match, we'll put the new
        # mapping.
        try:
            self.existing_mapping = self.conn.indices.get_mapping(index=self.index_name)
        except NotFoundError:
            pass
        except Exception:
            if not self.silently_fail:
                raise

        unified_index = haystack.connections[self.connection_alias].get_unified_index()
        self.content_field_name, field_mapping = self.build_schema(unified_index.all_searchfields())

        current_mapping = {
            'properties': field_mapping,
        }

        if current_mapping != self.existing_mapping:
            try:
                # Make sure the index is there first.
                self.conn.indices.create(index=self.index_name, body=self.DEFAULT_SETTINGS, ignore=400)
                self.conn.indices.put_mapping(index=self.index_name, body=current_mapping)
                self.existing_mapping = current_mapping
            except Exception:
                if not self.silently_fail:
                    raise

        self.setup_complete = True

    def update(self, index, iterable, commit=True):
        if not self.setup_complete:
            try:
                self.setup()
            except elasticsearch.TransportError as e:
                if not self.silently_fail:
                    raise

                self.log.error("Failed to add documents to Elasticsearch: %s", e, exc_info=True)
                return

        prepped_docs = []

        for obj in iterable:
            try:
                prepped_data = index.full_prepare(obj)
                final_data = {}

                # Convert the data to make sure it's happy.
                for key, value in prepped_data.items():
                    final_data[key] = self._from_python(value)
                final_data['_id'] = final_data[ID]

                prepped_docs.append(final_data)
            except SkipDocument:
                self.log.debug(u"Indexing for object `%s` skipped", obj)
            except elasticsearch.TransportError as e:
                if not self.silently_fail:
                    raise

                # We'll log the object identifier but won't include the actual object
                # to avoid the possibility of that generating encoding errors while
                # processing the log message:
                self.log.error(u"%s while preparing object for update" % e.__class__.__name__, exc_info=True,
                               extra={"data": {"index": index,
                                               "object": get_identifier(obj)}})

        bulk(self.conn, prepped_docs, index=self.index_name)

        if commit:
            self.conn.indices.refresh(index=self.index_name)

    def remove(self, obj_or_string, commit=True):
        doc_id = get_identifier(obj_or_string)

        if not self.setup_complete:
            try:
                self.setup()
            except elasticsearch.TransportError as e:
                if not self.silently_fail:
                    raise

                self.log.error("Failed to remove document '%s' from Elasticsearch: %s", doc_id, e,
                               exc_info=True)
                return

        try:
            self.conn.delete(index=self.index_name, id=doc_id, ignore=404)

            if commit:
                self.conn.indices.refresh(index=self.index_name)
        except elasticsearch.TransportError as e:
            if not self.silently_fail:
                raise

            self.log.error("Failed to remove document '%s' from Elasticsearch: %s", doc_id, e, exc_info=True)

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

    @log_query
    def search(self, query_string, **kwargs):
        if len(query_string) == 0:
            return {
                'results': [],
                'hits': 0,
            }

        if not self.setup_complete:
            self.setup()

        search_kwargs = self.build_search_kwargs(query_string, **kwargs)
        search_kwargs['from'] = kwargs.get('start_offset', 0)

        order_fields = set()
        for order in search_kwargs.get('sort', []):
            for key in order.keys():
                order_fields.add(key)

        geo_sort = '_geo_distance' in order_fields

        end_offset = kwargs.get('end_offset')
        start_offset = kwargs.get('start_offset', 0)
        if end_offset is not None and end_offset > start_offset:
            search_kwargs['size'] = end_offset - start_offset

        try:
            raw_results = self.conn.search(body=search_kwargs,
                                           index=self.index_name)
        except elasticsearch.TransportError as e:
            if not self.silently_fail:
                raise

            self.log.error("Failed to query Elasticsearch using '%s': %s", query_string, e, exc_info=True)
            raw_results = {}

        return self._process_results(raw_results,
                                     highlight=kwargs.get('highlight'),
                                     result_class=kwargs.get('result_class', SearchResult),
                                     distance_point=kwargs.get('distance_point'),
                                     geo_sort=geo_sort)

    def _process_results(self, raw_results, highlight=False,
                         result_class=None, distance_point=None,
                         geo_sort=False):
        results = super()._process_results(raw_results, highlight,
                                           result_class, distance_point,
                                           geo_sort)

        hits = raw_results.get('hits', {}).get('total', {}).get('value', 0)
        results['hits'] = hits

        return results


class Elasticsearch8SearchQuery(Elasticsearch6SearchQuery):
    pass


class Elasticsearch8SearchEngine(BaseEngine):
    backend = Elasticsearch8SearchBackend
    query = Elasticsearch8SearchQuery
