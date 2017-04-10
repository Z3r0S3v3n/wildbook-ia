# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals
import six
import numpy as np
import utool as ut
import itertools as it
import networkx as nx
from ibeis.algo.graph import nx_utils
from ibeis.algo.graph.nx_utils import e_
from ibeis.algo.graph.state import (POSTV, NEGTV, INCMP, UNREV)
from ibeis.algo.graph.nx_utils import (edges_inside, edges_cross,
                                       edges_outgoing)
print, rrr, profile = ut.inject2(__name__)


class DynamicUpdate(object):
    """
    # 12 total possible states

    # details of these states.
    POSITIVE, WITHIN, CONSISTENT
        * pos-within never changes PCC status
        * never introduces inconsistency
        * might add pos-redun
    POSITIVE, WITHIN, INCONSISTENT
        * pos-within never changes PCC status
        * might fix inconsistent edge
    POSITIVE, BETWEEN, BOTH_CONSISTENT
        * pos-between edge always does merge
    POSITIVE, BETWEEN, ANY_INCONSISTENT
        * pos-between edge always does merge
        * pos-between never fixes inconsistency

    NEGATIVE, WITHIN, CONSISTENT
        * might split PCC, results will be consistent
        * might causes an inconsistency
    NEGATIVE, WITHIN, INCONSISTENT
        * might split PCC, results may be inconsistent
    NEGATIVE, BETWEEN, BOTH_CONSISTENT
        * might add neg-redun
    NEGATIVE, BETWEEN, ANY_INCONSISTENT
        * might add to incon-neg-external
        * neg-redun not tracked for incon.

    INCOMPARABLE, WITHIN, CONSISTENT
        * might remove pos-redun
        * might split PCC, results will be consistent
    INCOMPARABLE, WITHIN, INCONSISTENT
        * might split PCC, results may be inconsistent
    INCOMPARABLE, BETWEEN, BOTH_CONSISTENT
        * might remove neg-redun
    INCOMPARABLE, BETWEEN, ANY_INCONSISTENT
        * might remove incon-neg-external
    """

    @profile
    def add_review_edge(infr, edge, decision):
        if decision == POSTV:
            infr._positive_decision(edge)
        elif decision == NEGTV:
            infr._negative_decision(edge)
        elif decision in (INCMP, UNREV):
            # incomparable and unreview have the same inference structure
            infr._uninferable_decision(edge, decision)
        else:
            raise AssertionError('Unknown decision=%r' % (decision,))
        # print('infr.recover_graph = %r' % (infr.recover_graph,))

    def _add_review_edges_from(infr, edges, decision):
        infr.print('add decision=%r from %d reviews' % (
            decision, len(edges)), 1)
        # Add to review graph corresponding to decision
        infr.review_graphs[decision].add_edges_from(edges)
        # Remove from previously existing graphs
        for k, G in infr.review_graphs.items():
            if k != decision:
                # print('replaced edge from %r graph' % (k,))
                G.remove_edges_from(edges)

    def _add_review_edge(infr, edge, decision):
        # infr.print('add review edge=%r, decision=%r' % (edge, decision), 20)
        # Add to review graph corresponding to decision
        infr.review_graphs[decision].add_edge(*edge)
        # Remove from previously existing graphs
        for k, G in infr.review_graphs.items():
            if k != decision:
                if G.has_edge(*edge):
                    # print('replaced edge from %r graph' % (k,))
                    G.remove_edge(*edge)

    def on_merge(infr, nid1, nid2, new_nid):
        cc = infr.pos_graph.component(new_nid)
        infr.set_node_attrs('name_label', ut.dzip(cc, [new_nid]))

    def on_split(infr, nid, new_nid1, new_nid2):
        cc1 = infr.pos_graph.component(new_nid1)
        cc2 = infr.pos_graph.component(new_nid2)
        infr.set_node_attrs('name_label', ut.dzip(cc1, [new_nid1]))
        infr.set_node_attrs('name_label', ut.dzip(cc2, [new_nid2]))

    def _positive_decision(infr, edge):
        r"""
        Ignore:
            >>> from ibeis.algo.graph.mixin_dynamic import *  # NOQA
            >>> from ibeis.algo.graph import demo
            >>> kwargs = dict(num_pccs=3, p_incon=0, size=100)
            >>> infr = demo.demodata_infr(infer=False, **kwargs)
            >>> infr.apply_nondynamic_update()
            >>> cc1 = next(infr.positive_components())

            %timeit list(infr.pos_graph.subgraph(cc1).edges())
            %timeit list(edges_inside(infr.pos_graph, cc1))
        """
        nid1, nid2 = infr.pos_graph.node_labels(*edge)
        incon1, incon2 = infr.recover_graph.has_nodes(edge)
        any_inconsistent = (incon1 or incon2)
        all_consistent = not any_inconsistent
        was_within = nid1 == nid2

        if was_within:
            infr._add_review_edge(edge, POSTV)
            if all_consistent:
                # infr.print('Internal consistent positive review')
                infr.print('pos-within-clean',)
                infr.update_pos_redun(nid1, may_remove=False)
            else:
                # infr.print('Internal inconsistent positive review')
                infr.print('pos-within-dirty',)
                infr._check_inconsistency(nid1)
        else:
            # infr.print('Merge case')
            cc1 = infr.pos_graph.component(nid1)
            cc2 = infr.pos_graph.component(nid2)

            infr._purge_redun_flags(nid1, nid2)

            if any_inconsistent:
                # infr.print('Inconsistent merge',)
                infr.print('pos-between-dirty-merge',)
                if not incon1:
                    recover_edges = list(edges_inside(infr.pos_graph, cc1))
                else:
                    recover_edges = list(edges_inside(infr.pos_graph, cc2))
                infr.recover_graph.add_edges_from(recover_edges)
                infr._add_review_edge(edge, POSTV)
                infr.recover_graph.add_edge(*edge)
                new_nid = infr.pos_graph.node_label(edge[0])
            elif any(edges_cross(infr.neg_graph, cc1, cc2)):
                # infr.print('Merge creates inconsistency',)
                infr.print('pos-between-clean-merge-dirty',)
                infr._add_review_edge(edge, POSTV)
                new_nid = infr.pos_graph.node_label(edge[0])
                infr._new_inconsistency(new_nid, POSTV)
            else:
                # infr.print('Consistent merge')
                infr.print('pos-between-clean-merge-clean',)
                infr._add_review_edge(edge, POSTV)
                new_nid = infr.pos_graph.node_label(edge[0])
                infr.update_extern_neg_redun(new_nid, may_remove=False)
                infr.update_pos_redun(new_nid, may_remove=False)

            infr.on_merge(nid1, nid2, new_nid)

    def _negative_decision(infr, edge):
        nid1, nid2 = infr.node_labels(*edge)
        incon1, incon2 = infr.recover_graph.has_nodes(edge)
        all_consistent = not (incon1 or incon2)
        infr._add_review_edge(edge, NEGTV)
        new_nid1, new_nid2 = infr.pos_graph.node_labels(*edge)

        was_within = nid1 == nid2
        was_split = was_within and new_nid1 != new_nid2

        # FIXME: REMOVING POSITIVE EDGES MIGHT CHANGE THE NAME LABEL EVEN IF
        # THE PCC IS NOT SPLIT

        if was_within:
            if was_split:
                if all_consistent:
                    # infr.print('Consistent split from negative')
                    infr.print('neg-within-split-clean',)
                    infr._purge_redun_flags(nid1)
                    infr.update_pos_redun(new_nid1, may_remove=False)
                    infr.update_pos_redun(new_nid2, may_remove=False)
                    infr.update_extern_neg_redun(new_nid1, may_remove=False)
                    infr.update_extern_neg_redun(new_nid2, may_remove=False)
                else:
                    # infr.print('Inconsistent split from negative')
                    infr.print('neg-within-split-dirty',)
                    if infr.recover_graph.has_edge(*edge):
                        infr.recover_graph.remove_edge(*edge)
                    infr._purge_error_edges(nid1)
                    infr._purge_redun_flags(nid1)
                    infr._check_inconsistency(new_nid1)
                    infr._check_inconsistency(new_nid2)
                # Signal that a split occurred
                infr.on_split(nid1, new_nid1, new_nid2)
            else:
                if all_consistent:
                    # infr.print('Negative added within clean PCC')
                    infr.print('neg-within-clean',)
                    infr._purge_redun_flags(new_nid1)
                    infr._new_inconsistency(new_nid1, NEGTV)
                else:
                    # infr.print('Negative added within inconsistent PCC')
                    infr.print('neg-within-dirty',)
                    pass
        else:
            if all_consistent:
                # infr.print('Negative added between consistent PCCs')
                infr.print('neg-between-clean',)
                infr.update_neg_redun(new_nid1, new_nid2, may_remove=False)
            else:
                # infr.print('Negative added external to inconsistent PCC')
                infr.print('neg-between-dirty',)
                # nothing to do if a negative edge is added between two PCCs
                # where at least one is inconsistent
                pass

    def _uninferable_decision(infr, edge, decision):
        """
        Adds either an incomparable or unreview decision
        """
        nid1, nid2 = infr.pos_graph.node_labels(*edge)
        incon1 = infr.recover_graph.has_node(edge[0])
        incon2 = infr.recover_graph.has_node(edge[1])
        all_consistent = not (incon1 or incon2)

        was_within = nid1 == nid2

        # FIXME: REMOVING POSITIVE EDGES MIGHT CHANGE THE NAME LABEL EVEN IF
        # THE PCC IS NOT SPLIT

        overwrote_positive = infr.pos_graph.has_edge(*edge)
        overwrote_negative = infr.neg_graph.has_edge(*edge)

        if decision == INCMP:
            prefix = 'incmp'
        elif decision == UNREV:
            prefix = 'unrev'
        else:
            raise KeyError('decision can only be UNREV or INCMP')

        infr._add_review_edge(edge, decision)

        if was_within:
            if overwrote_positive:
                # changed an existing positive edge
                if infr.recover_graph.has_edge(*edge):
                    infr.recover_graph.remove_edge(*edge)
                new_nid1, new_nid2 = infr.pos_graph.node_labels(*edge)
                was_split = new_nid1 != new_nid2
                if was_split:
                    old_nid = nid1
                    prev_neg_nids = infr._purge_redun_flags(old_nid)
                    if all_consistent:
                        # infr.print('Split CC from incomparable')
                        infr.print('%s-within-pos-split-clean' % prefix)
                        # split case
                        for other_nid in prev_neg_nids:
                            infr.update_neg_redun(new_nid1, other_nid)
                            infr.update_neg_redun(new_nid2, other_nid)
                        infr.update_neg_redun(new_nid1, new_nid2)
                        infr.update_pos_redun(new_nid1, may_remove=False)
                        infr.update_pos_redun(new_nid2, may_remove=False)
                    else:
                        # infr.print('Split inconsistent CC from incomparable')
                        infr.print('%s-within-pos-split-dirty',)
                        if infr.recover_graph.has_edge(*edge):
                            infr.recover_graph.remove_edge(*edge)
                        infr._purge_error_edges(nid1)
                        infr._check_inconsistency(new_nid1)
                        infr._check_inconsistency(new_nid2)
                    # Signal that a split occurred
                    infr.on_split(nid1, new_nid1, new_nid2)
                elif all_consistent:
                    # infr.print('Overwrote pos in CC with incomp')
                    infr.print('%s-within-pos-clean' % prefix)
                    infr.update_pos_redun(new_nid1, may_add=False)
                else:
                    # infr.print('Overwrote pos in inconsistent CC with incomp')
                    infr.print('%s-within-pos-dirty' % prefix)
                    # Overwriting a positive edge that is not a split
                    # in an inconsistent component, means no inference.
                    pass
            elif overwrote_negative:
                # infr.print('Overwrite negative within CC')
                infr.print('%s-within-neg-dirty' % prefix)
                assert not all_consistent
                infr._check_inconsistency(nid1)
            else:
                if all_consistent:
                    infr.print('%s-within-clean' % prefix)
                    # infr.print('Incomp edge within consistent CC')
                else:
                    infr.print('%s-within-dirty' % prefix)
                    # infr.print('Incomp edge within inconsistent CC')
        else:
            if overwrote_negative:
                if all_consistent:
                    # changed and existing negative edge only influences
                    # consistent pairs of PCCs
                    # infr.print('Overwrote neg edge between CCs')
                    infr.print('incon-between-neg-clean',)
                    infr.update_neg_redun(nid1, nid2, may_add=False)
                else:
                    infr.print('incon-between-neg-dirty',)
                    # infr.print('Overwrote pos edge between incon CCs')
            else:
                infr.print('incon-between',)
                # infr.print('Incomp edge between CCs')


class Recovery(object):
    """ recovery funcs """

    def is_recovering(infr):
        return len(infr.recover_graph) > 0

    def _purge_error_edges(infr, nid):
        old_error_edges = infr.nid_to_errors.pop(nid, [])
        # Remove priority from old error edges
        infr.set_edge_attrs('maybe_error', ut.dzip(old_error_edges, [None]))
        if infr.queue is not None:
            infr._remove_edge_priority(old_error_edges)
            # for error_edge in old_error_edges:
            #     infr.queue[error_edge] = 0

    def _set_error_edges(infr, nid, new_error_edges):
        # flag error edges
        infr.nid_to_errors[nid] = new_error_edges
        # choose one and give it insanely high priority
        infr.set_edge_attrs('maybe_error', ut.dzip(new_error_edges, [True]))
        if infr.queue is not None:
            for error_edge in new_error_edges:
                data = infr.graph.get_edge_data(*error_edge)
                base = data.get('prob_match', 1e-9)
                infr.queue[error_edge] = -(10 + base)

    def _new_inconsistency(infr, nid, from_):
        cc = infr.pos_graph.component(nid)
        pos_edges = infr.pos_graph.edges(cc)
        infr.recover_graph.add_edges_from(pos_edges)
        # num = len(list(nx.connected_components(infr.recover_graph)))
        num = infr.recover_graph.number_of_components()
        msg = 'New inconsistency from {}, {} total'.format(from_, num)
        infr.print(msg, color='red')
        infr._check_inconsistency(nid, cc=cc)

    def _check_inconsistency(infr, nid, cc=None):
        if cc is None:
            cc = infr.pos_graph.component(nid)
        # infr.print('Checking consistency of {}'.format(nid))
        pos_subgraph = infr.pos_graph.subgraph(cc)
        if not nx.is_connected(pos_subgraph):
            print('cc = %r' % (cc,))
            print('pos_subgraph = %r' % (pos_subgraph,))
            raise AssertionError('must be connected')
        infr._purge_error_edges(nid)
        neg_edges = list(edges_inside(infr.neg_graph, cc))
        if neg_edges:
            hypothesis = dict(infr.hypothesis_errors(
                pos_subgraph.copy(), neg_edges))
            assert len(hypothesis) > 0, 'must have at least one'
            infr._set_error_edges(nid, set(hypothesis.keys()))
        else:
            infr.recover_graph.remove_nodes_from(cc)
            num = infr.recover_graph.number_of_components()
            # num = len(list(nx.connected_components(infr.recover_graph)))
            msg = ('An inconsistent PCC recovered, '
                   '{} inconsistent PCC(s) remain').format(num)
            infr.print(msg, color='green')
            infr.update_pos_redun(nid, force=True)
            infr.update_extern_neg_redun(nid, force=True)

    @profile
    def hypothesis_errors(infr, pos_subgraph, neg_edges):
        if not nx.is_connected(pos_subgraph):
            raise AssertionError('Not connected' + repr(pos_subgraph))
        infr.print(
            'Find hypothesis errors in {} nodes with {} neg edges'.format(
                len(pos_subgraph), len(neg_edges)), 2)

        pos_edges = list(pos_subgraph.edges())

        # Generate weights for edges
        default = 0
        # default = 1e-6
        pos_gen = infr.gen_edge_values('prob_match', pos_edges, default=default)
        neg_gen = infr.gen_edge_values('prob_match', neg_edges, default=default)
        pos_prob = list(pos_gen)
        neg_prob = list(neg_gen)
        pos_n = list(infr.gen_edge_values('num_reviews', pos_edges, default=0))
        neg_n = list(infr.gen_edge_values('num_reviews', neg_edges, default=0))
        pos_weight = pos_n
        neg_weight = neg_n
        pos_weight = np.add(pos_prob, np.array(pos_n))
        neg_weight = np.add(neg_prob, np.array(neg_n))
        capacity = 'weight'
        nx.set_edge_attributes(pos_subgraph, capacity,
                               ut.dzip(pos_edges, pos_weight))

        # Solve a multicut problem for multiple pairs of terminal nodes.
        # Running multiple min-cuts produces a k-factor approximation
        maybe_error_edges = set([])
        for (s, t), join_weight in zip(neg_edges, neg_weight):
            cut_weight, parts = nx.minimum_cut(pos_subgraph, s, t,
                                               capacity=capacity)
            cut_edgeset = edges_cross(pos_subgraph, *parts)
            # cut_edgeset_weight = sum([
            #     pos_subgraph.get_edge_data(u, v)[capacity]
            #     for u, v in cut_edgeset])
            # infr.print('cut_weight = %r' % (cut_weight,), 3)
            # infr.print('join_weight = %r' % (join_weight,), 3)
            if join_weight < cut_weight:
                join_edgeset = {(s, t)}
                chosen = join_edgeset
                hypothesis = POSTV
            else:
                chosen = cut_edgeset
                hypothesis = NEGTV
            for edge in chosen:
                if edge not in maybe_error_edges:
                    maybe_error_edges.add(edge)
                    yield (edge, hypothesis)
        # return maybe_error_edges


class Consistency(object):
    def is_consistent(infr, cc):
        r"""
        Determines if a PCC contains inconsistencies

        Args:
            cc (set): nodes in a PCC

        Returns:
            flag: bool: returns True unless cc contains any negative edges

        Example:
            >>> # ENABLE_DOCTEST
            >>> from ibeis.algo.graph import demo
            >>> infr = demo.demodata_infr(num_pccs=1, p_incon=1)
            >>> assert not infr.is_consistent(next(infr.positive_components()))
            >>> infr = demo.demodata_infr(num_pccs=1, p_incon=0)
            >>> assert infr.is_consistent(next(infr.positive_components()))
        """
        return len(cc) <= 2 or not any(edges_inside(infr.neg_graph, cc))

    def positive_components(infr, graph=None):
        r"""
        Generates the positive connected compoments (PCCs) in the graph
        These will contain both consistent and inconsinstent PCCs.

        Yields:
            cc: set: nodes within the PCC
        """
        pos_graph = infr.pos_graph
        if graph is None or graph is infr.graph:
            ccs = pos_graph.connected_components()
        else:
            unique_labels = {
                pos_graph.node_label(node) for node in graph.nodes()}
            ccs = (pos_graph.connected_to(node) for node in unique_labels)
        for cc in ccs:
            yield cc

    def inconsistent_components(infr, graph=None):
        """
        Generates inconsistent PCCs.
        These PCCs contain internal negative edges indicating an error exists.
        """
        for cc in infr.positive_components(graph):
            if not infr.is_consistent(cc):
                yield cc

    def consistent_components(infr, graph=None):
        r"""
        Generates consistent PCCs.
        These PCCs contain no internal negative edges.

        Yields:
            cc: set: nodes within the PCC
        """
        # Find PCCs without any negative edges
        for cc in infr.positive_components(graph):
            if infr.is_consistent(cc):
                yield cc


class Completeness(object):
    @profile
    def prob_complete(infr, cc):
        if infr.term is None:
            assert False
            return 0
        else:
            size = len(cc)
            # Choose most appropriate phi
            if size not in infr.term.phis:
                size = max(infr.term.phis.keys())
            phi = infr.term.phis[size]
            # pos_graph.node_label()
            num_ccs = len(infr.pos_graph._ccs)
            # We use annot scores because names could be different if
            # reviews have happened.
            ranked_aids = infr._get_cm_agg_aid_ranking(cc)
            # Map these aids onto current nid label
            ranked_nids = ut.unique(
                [infr.pos_graph.node_label(aid) for aid in ranked_aids])
            nid_to_rank = ut.make_index_lookup(ranked_nids)
            neg_nid_neighbors = set(infr.negative_redundant_nids(cc))
            # Get the ranks of known negative neighbors
            neg_ranks = [rank for nid, rank in nid_to_rank.items()
                         if nid in neg_nid_neighbors]
            neg_ranks = sorted(neg_ranks)
            slack = num_ccs - len(phi)
            if slack:
                phi = np.append(phi, [phi[-1]] * slack)
                phi = phi / phi.sum()
            # TODO: extend phi if needed for current dbsize
            p_complete = sum([phi[r] for r in neg_ranks])
            return p_complete

    @profile
    def check_prob_completeness(infr, node):
        """
            >>> from ibeis.algo.graph.mixin_dynamic import *  # NOQA
            >>> import plottool as pt
            >>> pt.qtensure()
            >>> infr = testdata_infr2()
            >>> infr.initialize_visual_node_attrs()
            >>> #ut.ensureqt()
            >>> #infr.show()
            >>> infr.refresh_candidate_edges()
            >>> node = 1
            >>> node = 20
            >>> infr.is_node_complete(node)
        """
        thresh = infr.queue_params['complete_thresh']
        cc = infr.pos_graph.connected_to(node)
        if thresh < 1.0:
            p_complete = infr.prob_complete(cc)
            if p_complete > thresh:
                return True
        return False

    @profile
    def non_complete_pcc_pairs(infr):
        """
        Get pairs of PCCs that are not complete.
        Finds edges that might complete them.

        Example:
            >>> # DISABLE_DOCTEST
            >>> from ibeis.algo.graph.mixin_dynamic import *  # NOQA
            >>> infr = testdata_infr2()
            >>> categories = infr.categorize_edges(graph)
            >>> negative = categories[NEGTV]
            >>> ne, edges = #list(categories['reviewed_negatives'].items())[0]
            >>> infr.graph.remove_edges_from(edges)
            >>> cc1, cc2, _edges = list(infr.non_complete_pcc_pairs())[0]
            >>> result = non_complete_pcc_pairs(infr)
            >>> print(result)
        """
        thresh = infr.queue_params['complete_thresh']
        pcc_set = list(infr.positive_connected_compoments())
        # Remove anything under the probabilistic threshold
        if thresh < 1.0:
            pcc_set = [
                c1 for c1 in pcc_set if
                infr.prob_complete(c1) < thresh
            ]
        else:
            assert False
        # Loop through all pairs
        for c1_nodes, c2_nodes in it.combinations(pcc_set, 2):
            check_edges = infr.rand_neg_check_edges(c1_nodes, c2_nodes)
            if len(check_edges) > 0:
                # no check edges means we can't do anything
                yield (c1_nodes, c2_nodes, check_edges)


class Priority(object):

    def remaining_reviews(infr):
        assert infr.queue is not None
        return len(infr.queue)

    def prioritize(infr, metric=None):
        if infr.queue is None:
            infr.queue = ut.PriorityQueue()
        low = 1e-9
        metric = 'prob_match'
        # Get unreviewed and error edges that are not redundant
        edges = list(infr.filter_nonredun_edges(infr.unreviewed_graph.edges()))
        priorities = list(infr.gen_edge_values(metric, edges, default=low))
        priorities = np.array(priorities)
        priorities[np.isnan(priorities)] = low
        num_new = 0
        for edge, priority in zip(edges, priorities):
            if edge not in infr.queue:
                num_new += 1
            infr.queue[edge] = -priority
        # Increase priority of any edge flagged as maybe_error
        for edge in ut.iflatten(infr.nid_to_errors.values()):
            if edge not in infr.queue:
                num_new += 1
            infr.queue[edge] = infr.queue.pop(edge, low) - 10
        infr.print('added %d edges to the queue' % (num_new,))

    def pop(infr):
        try:
            edge, priority = infr.queue.pop()
        except IndexError:
            raise StopIteration('no more to review!')
        else:
            assert edge[0] < edge[1]
            return edge, (priority * -1)

    def generate_reviews(infr, pos_redun=None, neg_redun=None,
                         data=False):
        """
        Dynamic generator that yeilds high priority reviews
        """
        if pos_redun is not None:
            infr.queue_params['pos_redun'] = pos_redun
        if neg_redun is not None:
            infr.queue_params['neg_redun'] = neg_redun
        infr.prioritize()
        return infr._generate_reviews(data=data)

    def _generate_reviews(infr, data=False):
        if data:
            while True:
                if len(infr.queue) == 0:
                    pass
                edge, priority = infr.pop()
                yield edge, priority
        else:
            while True:
                edge, priority = infr.pop()
                yield edge

    def remove_internal_priority(infr, cc):
        infr._remove_edge_priority(edges_inside(infr.graph, cc))

    def remove_external_priority(infr, cc):
        infr._remove_edge_priority(edges_outgoing(infr.graph, cc))

    def remove_between_priority(infr, cc1, cc2):
        infr._remove_edge_priority(edges_cross(infr.graph, cc1, cc2))

    def reinstate_between_priority(infr, cc1, cc2):
        # Reinstate the appropriate edges into the queue
        edges = edges_cross(infr.unreviewed_graph, cc1, cc2)
        infr._reinstate_edge_priority(edges)

    def reinstate_internal_priority(infr, cc):
        # Reinstate the appropriate edges into the queue
        edges = edges_inside(infr.unreviewed_graph, cc)
        infr._reinstate_edge_priority(edges)

    def reinstate_external_priority(infr, cc):
        # Reinstate the appropriate edges into the queue
        edges = edges_outgoing(infr.unreviewed_graph, cc)
        infr._reinstate_edge_priority(edges)

    def _remove_edge_priority(infr, edges):
        edges = [edge for edge in edges if edge in infr.queue]
        infr.print('removed priority from %d edges' % (len(edges),))
        infr.queue.delete_items(edges)

    def _reinstate_edge_priority(infr, edges):
        edges = [edge for edge in edges if edge not in infr.queue]
        prob_match = np.array(list(infr.gen_edge_values(
            'prob_match', edges, default=1e-9)))
        priority = -prob_match
        infr.print('reinstate priority from %d edges' % (len(edges),))
        infr.queue.update(ut.dzip(edges, priority))


@six.add_metaclass(ut.ReloadingMetaclass)
class _RedundancyHelpers(object):
    """ methods for computing redundancy """

    @profile
    def rand_neg_check_edges(infr, c1_nodes, c2_nodes):
        """
        Find enough edges to between two pccs to make them k-negative complete
        """
        k = infr.queue_params['neg_redun']
        existing_edges = edges_cross(infr.graph, c1_nodes, c2_nodes)
        reviewed_edges = {
            edge: state
            for edge, state in infr.get_edge_attrs(
                'decision', existing_edges,
                default=UNREV).items()
            if state != UNREV
        }
        n_neg = sum([state == NEGTV for state in reviewed_edges.values()])
        if n_neg < k:
            # Find k random negative edges
            check_edges = existing_edges - set(reviewed_edges)
            if len(check_edges) < k:
                for edge in it.starmap(e_, it.product(c1_nodes, c2_nodes)):
                    if edge not in reviewed_edges:
                        check_edges.add(edge)
                        if len(check_edges) == k:
                            break
        else:
            check_edges = {}
        return check_edges

    def find_external_neg_nids(infr, cc):
        """
        Find the nids with at least one negative edge external
        to this cc.
        """
        pos_graph = infr.pos_graph
        neg_graph = infr.neg_graph
        out_neg_nids = set([])
        for u in cc:
            nid1 = pos_graph.node_label(u)
            for v in neg_graph.neighbors(u):
                nid2 = pos_graph.node_label(v)
                if nid1 == nid2 and v not in cc:
                    continue
                out_neg_nids.add(nid2)
        return out_neg_nids

    def find_external_neg_nid_freq(infr, cc):
        """
        Find the number of edges leaving `cc` and directed towards specific
        names.
        """
        pos_graph = infr.pos_graph
        neg_graph = infr.neg_graph
        neg_nid_freq = ut.ddict(lambda: 0)
        for u in cc:
            nid1 = pos_graph.node_label(u)
            for v in neg_graph.neighbors(u):
                nid2 = pos_graph.node_label(v)
                if nid1 == nid2 and v not in cc:
                    continue
                neg_nid_freq[nid2] += 1
        return neg_nid_freq


@six.add_metaclass(ut.ReloadingMetaclass)
class Redundancy(_RedundancyHelpers):
    """ methods for computing redundancy """

    def _purge_redun_flags(infr, *nids):
        """
        Removes positive and negative redundancy from nids and all other PCCs
        touching nids respectively. Return the external PCC nids.
        """
        neighbs = (infr.neg_redun_nids.neighbors(nid) for nid in nids
                   if infr.neg_redun_nids.has_node(nid))
        prev_neg_nids = set(ut.iflatten(neighbs))
        prev_neg_nids -= set(nids)
        infr.neg_redun_nids.remove_nodes_from(nids)
        infr.pos_redun_nids.difference_update(set(nids))
        return prev_neg_nids

    def update_extern_neg_redun(infr, nid, may_add=True, may_remove=True,
                                force=False):
        k_neg = infr.queue_params['neg_redun']
        cc1 = infr.pos_graph.component(nid)
        if force or True:
            # TODO: non-force versions
            freqs = infr.find_external_neg_nid_freq(cc1)
            for other_nid, freq in freqs.items():
                if freq >= k_neg:
                    cc2 = infr.pos_graph.component(other_nid)
                    infr.neg_redun_nids.add_edge(nid, other_nid)
                    if infr.queue is not None:
                        infr.remove_between_priority(cc1, cc2)
                elif may_remove:
                    try:
                        infr.neg_redun_nids.remove_edge(nid, other_nid)
                    except nx.exception.NetworkXError:
                        pass
                    else:
                        if infr.queue is not None:
                            infr.reinstate_between_priority(cc1, cc2)

    @profile
    def update_neg_redun(infr, nid1, nid2, may_add=True, may_remove=True,
                         force=False):
        """
        Checks if two PCCs are newly or no longer negative redundant.
        Edges are either removed or added to the queue appropriately.
        """
        infr.print('update_neg_redun')
        need_add = False
        need_remove = False
        force = True
        was_neg_redun = infr.neg_redun_nids.has_edge(nid1, nid2)
        if force:
            cc1 = infr.pos_graph.component(nid1)
            cc2 = infr.pos_graph.component(nid2)
            need_add = infr.is_neg_redundant(cc1, cc2)
            need_remove = not need_add
        else:
            if may_add and not was_neg_redun:
                cc1 = infr.pos_graph.component(nid1)
                cc2 = infr.pos_graph.component(nid2)
                need_add = infr.is_neg_redundant(cc1, cc2)
            elif may_remove and not was_neg_redun:
                need_remove = not infr.is_neg_redundant(cc1, cc2)
        # if force:
        #     infr.print('is_neg_redun=%r' % (need_add,))
        if need_add:
            # Flag ourselves as negative redundant and remove priorities
            if not was_neg_redun:
                infr.print('flag_neg_redun=%r,%r' % (nid1, nid2,))
            infr.neg_redun_nids.add_edge(nid1, nid2)
            if infr.queue is not None:
                infr.remove_between_priority(cc1, cc2)
        elif need_remove:
            if was_neg_redun:
                infr.print('unflag_neg_redun=%r,%r' % (nid1, nid2,))
            try:
                infr.neg_redun_nids.remove_edge(nid1, nid2)
            except nx.exception.NetworkXError:
                pass
            cc1 = infr.pos_graph.component(nid1)
            cc2 = infr.pos_graph.component(nid2)
            if infr.queue is not None:
                infr.reinstate_between_priority(cc1, cc2)

    def update_pos_redun(infr, nid, may_add=True, may_remove=True,
                         force=False):
        """
        Checks if a PCC is newly, or no longer positive redundant.
        Edges are either removed or added to the queue appropriately.
        """
        infr.print('update_pos_redun')
        need_add = False
        need_remove = False
        if force:
            cc = infr.pos_graph.component(nid)
            need_add = infr.is_pos_redundant(cc)
            need_remove = not need_add
        else:
            was_pos_redun = nid in infr.pos_redun_nids
            if may_add and not was_pos_redun:
                cc = infr.pos_graph.component(nid)
                need_add = infr.is_pos_redundant(cc)
            elif may_remove and not was_pos_redun:
                need_remove = not infr.is_pos_redundant(cc)
        if need_add:
            # If checks pass, flag nid as pos-redun
            infr.pos_redun_nids.add(nid)
            if infr.queue is not None:
                infr.remove_internal_priority(cc)
        elif need_remove:
            # If the checks fails then, unflag the nid
            infr.pos_redun_nids -= {nid}
            if infr.queue is not None:
                infr.reinstate_internal_priority(cc)

    def negative_redundant_nids(infr, cc):
        """
        Get PCCs that are k-negative redundant with `cc`

            >>> from ibeis.algo.graph.mixin_dynamic import *  # NOQA
            >>> import plottool as pt
            >>> pt.qtensure()
            >>> infr = testdata_infr2()
            >>> node = 20
            >>> cc = infr.pos_graph.connected_to(node)
            >>> infr.queue_params['neg_redun'] = 2
            >>> infr.negative_redundant_nids(cc)
        """
        neg_nid_freq = infr.find_external_neg_nid_freq(cc)
        # check for k-negative redundancy
        k_neg = infr.queue_params['neg_redun']
        pos_graph = infr.pos_graph
        neg_nids = [
            nid2 for nid2, freq in neg_nid_freq.items()
            if (
                freq >= k_neg or
                freq == len(cc) or
                freq == len(pos_graph.connected_to(nid2))
            )
        ]
        return neg_nids

    def pos_redundant_pccs(infr, relax_size=False):
        for cc in infr.consistent_components():
            if len(cc) == 2:
                continue
            if infr.is_pos_redundant(cc, relax_size):
                yield cc

    def non_pos_redundant_pccs(infr, relax_size=False):
        """
        Get PCCs that are not k-positive-redundant
        """
        for cc in infr.consistent_components():
            if not infr.is_pos_redundant(cc, relax_size):
                yield cc

    def find_pos_redun_nids(infr):
        """ recomputes infr.pos_redun_nids """
        for cc in infr.pos_redundant_pccs():
            node = next(iter(cc))
            nid = infr.pos_graph.node_label(node)
            yield nid

    def find_neg_redun_nids(infr):
        """ recomputes edges in infr.neg_redun_nids """
        for cc in infr.consistent_components():
            node = next(iter(cc))
            nid1 = infr.pos_graph.node_label(node)
            for nid2 in infr.negative_redundant_nids(cc):
                if nid1 < nid2:
                    yield nid1, nid2

    def is_pos_redundant(infr, cc, relax_size=False):
        k = infr.queue_params['pos_redun']
        if k == 1:
            return True  # assumes cc is connected
        else:
            # if the nodes are not big enough for this amount of connectivity
            # then we relax the requirement
            if relax_size:
                required_k = min(len(cc) - 1, k)
            else:
                required_k = k
            assert isinstance(cc, set)
            if required_k <= 1:
                return True
            else:
                pos_subgraph = infr.pos_graph.subgraph(cc)
                nx_utils.is_edge_connected(pos_subgraph, k=required_k)

    def is_neg_redundant(infr, cc1, cc2):
        r"""
        Tests if two groups of nodes are negative redundant
        (ie. have at least k negative edges between them).

        Example:
            >>> # ENABLE_DOCTEST
            >>> from ibeis.algo.graph.mixin_dynamic import *  # NOQA
            >>> from ibeis.algo.graph import demo
            >>> infr = demo.make_demo_infr(ccs=[(1, 2), (3, 4)])
            >>> infr.queue_params['neg_redun'] = 2
            >>> cc1 = infr.pos_graph.connected_to(1)
            >>> cc2 = infr.pos_graph.connected_to(3)
            >>> flag1 = infr.is_neg_redundant(cc1, cc2)
            >>> infr.add_feedback((1, 3), decision=NEGTV)
            >>> flag2 = infr.is_neg_redundant(cc1, cc2)
            >>> infr.add_feedback((2, 4), decision=NEGTV)
            >>> flag3 = infr.is_neg_redundant(cc1, cc2)
            >>> flags = [flag1, flag2, flag3]
            >>> print('flags = %r' % (flags,))
            >>> assert flags == [False, False, True]
        """
        k_neg = infr.queue_params['neg_redun']
        neg_edge_gen = edges_cross(infr.neg_graph, cc1, cc2)
        # do a lazy count of negative edges
        for count, _ in enumerate(neg_edge_gen, start=1):
            if count >= k_neg:
                return True
        return False

    # def pos_redun_edge_flag(infr, edge):
    #     """ Quickly check if edge is flagged as pos redundant """
    #     nid1, nid2 = infr.pos_graph.node_labels(*edge)
    #     return nid1 == nid2 and nid1 in infr.pos_redun_nids

    # def neg_redun_edge_flag(infr, edge):
    #     """ Quickly check if edge is flagged as neg redundant """
    #     nid1, nid2 = infr.pos_graph.node_labels(*edge)
    #     return infr.neg_redun_nids.has_edge(nid1, nid2)

    @profile
    def is_redundant(infr, edge):
        nidu, nidv = infr.node_labels(*edge)
        if nidu == nidv:
            if nidu in infr.pos_redun_nids:
                return True
        elif nidu != nidv:
            if infr.neg_redun_nids.has_edge(nidu, nidv):
                return True
        return False

    def filter_nonredun_edges(infr, edges):
        """
        Example:
            >>> # ENABLE_DOCTEST
            >>> from ibeis.algo.graph.mixin_dynamic import *  # NOQA
            >>> from ibeis.algo.graph import demo
            >>> infr = demo.demodata_infr(num_pccs=1, size=4)
            >>> infr.clear_edges()
            >>> infr.ensure_cliques()
            >>> infr.clear_feedback()
            >>> print(ut.repr4(infr.status()))
            >>> nonredun_edges = list(infr.filter_nonredun_edges(
            >>>     infr.unreviewed_graph.edges()))
            >>> assert len(nonredun_edges) == 6
        """
        for edge in edges:
            if not infr.is_redundant(edge):
                yield edge


@six.add_metaclass(ut.ReloadingMetaclass)
class NonDynamicUpdate(object):
    def apply_nondynamic_update(infr, graph=None):
        r"""
        Recomputes all dynamic bookkeeping for a graph in any state.
        This ensures that subsequent dyanmic inference can be applied.
        """
        categories = infr.categorize_edges(graph)

        infr.recover_graph.clear()
        nid_to_errors = {}
        for nid, intern_edges in categories['inconsistent_internal'].items():
            cc = infr.pos_graph.component_nodes(nid)
            pos_subgraph = infr.pos_graph.subgraph(cc).copy()
            neg_edges = list(edges_inside(infr.neg_graph, cc))
            recover_hypothesis = dict(infr.hypothesis_errors(
                pos_subgraph, neg_edges))
            nid_to_errors[nid] = set(recover_hypothesis.keys())
            infr.recover_graph.add_edges_from(pos_subgraph.edges())

        infr.set_edge_attrs(
            'inferred_state',
            ut.dzip(ut.flatten(categories[POSTV].values()), ['same'])
        )
        infr.set_edge_attrs(
            'inferred_state',
            ut.dzip(ut.flatten(categories[NEGTV].values()), ['diff'])
        )
        infr.set_edge_attrs(
            'inferred_state',
            ut.dzip(ut.flatten(categories[INCMP].values()), [INCMP])
        )
        infr.set_edge_attrs(
            'inferred_state',
            ut.dzip(ut.flatten(categories[UNREV].values()), [None])
        )
        infr.set_edge_attrs(
            'inferred_state',
            ut.dzip(ut.flatten(categories['inconsistent_internal'].values()),
                    ['inconsistent_internal'])
        )
        infr.set_edge_attrs(
            'inferred_state',
            ut.dzip(ut.flatten(categories['inconsistent_external'].values()),
                    ['inconsistent_external'])
        )
        # assert (
        #     set(ut.flatten(ut.flatten(categories['inconsistent_internal'].values()))) ==
        #     set(ut.flatten(infr.recovery_ccs))
        # )

        # Delete old hypothesis
        infr.set_edge_attrs(
            'maybe_error',
            ut.dzip(ut.flatten(infr.nid_to_errors.values()), [None])
        )
        # Set new hypothesis
        infr.set_edge_attrs(
            'maybe_error',
            ut.dzip(ut.flatten(nid_to_errors.values()), [True])
        )
        infr.nid_to_errors = nid_to_errors

        # TODO: should this also update redundancy?
        # infr.refresh_bookkeeping()
        # def refresh_bookkeeping(infr):
        # TODO: need to ensure bookkeeping is taken care of
        infr.recovery_ccs = list(infr.inconsistent_components())
        if len(infr.recovery_ccs) > 0:
            infr.recovery_cc = infr.recovery_ccs[0]
            infr.recover_prev_neg_nids = list(
                infr.find_external_neg_nids(infr.recovery_cc)
            )
        else:
            infr.recovery_cc = None
            infr.recover_prev_neg_nids = None
        infr.pos_redun_nids = set(infr.find_pos_redun_nids())
        infr.neg_redun_nids = infr._graph_cls(list(infr.find_neg_redun_nids()))

    @profile
    def categorize_edges(infr, graph=None):
        r"""
        Non-dynamically computes the status of each edge in the graph.
        This is can be used to verify the dynamic computations and update when
        the dynamic state is lost.

        CommandLine:
            python -m ibeis.algo.graph.mixin_dynamic categorize_edges --profile

        Example:
            >>> # ENABLE_DOCTEST
            >>> from ibeis.algo.graph.mixin_dynamic import *  # NOQA
            >>> from ibeis.algo.graph import demo
            >>> num_pccs = 250 if ut.get_argflag('--profile') else 100
            >>> kwargs = dict(num_pccs=100, p_incon=.3)
            >>> infr = demo.demodata_infr(infer=False, **kwargs)
            >>> graph = None
            >>> cat = infr.categorize_edges()
        """
        states = (POSTV, NEGTV, INCMP, UNREV)
        rev_graph = {key: infr.review_graphs[key] for key in states}
        if graph is None or graph is infr.graph:
            graph = infr.graph
            nodes = None
        else:
            # Need to extract relevant subgraphs
            nodes = list(graph.nodes())
            for key in states:
                rev_graph[key] = rev_graph[key].subgraph(nodes)

        # TODO: Rebalance union find to ensure parents is a single lookup
        # infr.pos_graph._union_find.rebalance(nodes)
        # node_to_label = infr.pos_graph._union_find.parents
        node_to_label = infr.pos_graph._union_find

        # Get reviewed edges using fast lookup structures
        ne_to_edges = {
            key: nx_utils.group_name_edges(rev_graph[key], node_to_label)
            for key in states
        }

        # Use reviewed edges to determine status of PCCs (repr by name ids)
        # The next steps will rectify duplicates in these sets
        name_edges = {key: set(ne_to_edges[key].keys()) for key in states}

        # Positive and negative decisions override incomparable and unreviewed
        for key in (INCMP, UNREV):
            name_edges[key].difference_update(name_edges[POSTV])
            name_edges[key].difference_update(name_edges[NEGTV])

        # Negative edges within a PCC signals that an inconsistency exists
        # Remove inconsistencies from the name edges
        incon_internal_ne = name_edges[NEGTV].intersection(name_edges[POSTV])
        name_edges[POSTV].difference_update(incon_internal_ne)
        name_edges[NEGTV].difference_update(incon_internal_ne)

        if __debug__:
            assert all(n1 == n2 for n1, n2 in name_edges[POSTV]), (
                'All positive edges should be internal to a PCC')
            assert len(name_edges[INCMP].intersection(incon_internal_ne)) == 0
            assert len(name_edges[UNREV].intersection(incon_internal_ne)) == 0
            assert all(n1 == n2 for n1, n2 in incon_internal_ne), (
                'incon_internal edges should be internal to a PCC')

        # External inconsistentices are edges leaving inconsistent components
        incon_internal_nids = {n1 for n1, n2 in incon_internal_ne}
        incon_external_ne = set([])
        # Find all edges leaving an inconsistent PCC
        for key in (NEGTV, INCMP, UNREV):
            incon_external_ne.update({
                (nid1, nid2) for nid1, nid2 in name_edges[key]
                if nid1 in incon_internal_nids or nid2 in incon_internal_nids
            })
        for key in (NEGTV, INCMP, UNREV):
            name_edges[key].difference_update(incon_external_ne)

        # Inference between names is now complete.
        # Now we expand this inference and project the labels onto the
        # annotation edges corresponding to each name edge.

        # Version of union that accepts generators
        union = lambda gen: set.union(*gen)  # NOQA

        # Find edges within consistent PCCs
        positive = {
            nid1: union(
                ne_to_edges[key][(nid1, nid2)]
                for key in (POSTV, INCMP, UNREV))
            for nid1, nid2 in name_edges[POSTV]
        }
        # Find edges between 1-negative-redundant consistent PCCs
        negative = {
            (nid1, nid2): union(
                ne_to_edges[key][(nid1, nid2)]
                for key in (NEGTV, INCMP, UNREV))
            for nid1, nid2 in name_edges[NEGTV]
        }
        # Find edges internal to inconsistent PCCs
        incon_internal = {
            nid: union(
                ne_to_edges[key][(nid, nid)]
                for key in (POSTV, NEGTV, INCMP, UNREV))
            for nid in incon_internal_nids
        }
        # Find edges leaving inconsistent PCCs
        incon_external = {
            (nid1, nid2): union(
                ne_to_edges[key][(nid1, nid2)]
                for key in (NEGTV, INCMP, UNREV))
            for nid1, nid2 in incon_external_ne
        }
        # Incomparable names cannot make inference about any other edges
        notcomparable = {
            (nid1, nid2): ne_to_edges[INCMP][(nid1, nid2)]
            for (nid1, nid2) in name_edges[INCMP]
        }
        # Unreviewed edges are between any name not known to be negative
        # (this ignores specific incomparable edges)
        unreviewed = {
            (nid1, nid2): ne_to_edges[UNREV][(nid1, nid2)]
            for (nid1, nid2) in name_edges[UNREV]
        }

        ne_categories = {
            POSTV: positive,
            NEGTV: negative,
            UNREV: unreviewed,
            INCMP: notcomparable,
            'inconsistent_internal': incon_internal,
            'inconsistent_external': incon_external,
        }
        return ne_categories


if __name__ == '__main__':
    r"""
    CommandLine:
        python -m ibeis.algo.graph.dynamic_review
        python -m ibeis.algo.graph.dynamic_review --allexamples
    """
    import multiprocessing
    multiprocessing.freeze_support()  # for win32
    import utool as ut  # NOQA
    ut.doctest_funcs()