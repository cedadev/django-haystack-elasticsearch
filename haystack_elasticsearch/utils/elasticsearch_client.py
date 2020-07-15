# encoding: utf-8
"""
Simple function to abstract the implementation of the client to allow a
quick swap to another implementation if desired.
"""
__author__ = 'Richard Smith'
__date__ = '13 Jul 2020'
__copyright__ = 'Copyright 2018 United Kingdom Research and Innovation'
__license__ = 'BSD - see LICENSE file in top-level package directory'
__contact__ = 'richard.d.smith@stfc.ac.uk'

from ceda_elasticsearch_tools.elasticsearch import CEDAElasticsearchClient


def get_elasticsearch_client(**kwargs):
    """
    Returns and Elasticsearch client object.
    Used to abstract the precise client implementation.
    """
    return CEDAElasticsearchClient(**kwargs)
