from copy import deepcopy
from scripts.compare_track_classification import compare_previous_report


def test_comparison_only_counts_identical_inputs_as_policy_changes():
    original={'source':['test','board'],'external_id':'a','input_sha256':'same', 'candidate':{'matched_tracks':[], 'decisions':[{'track':'computer_science','degree_color':'red'}]},'review_tracks':['computer_science']}
    current=deepcopy(original);current['candidate']['matched_tracks']=['computer_science'];current['review_tracks']=[]
    modified=deepcopy(current);modified['input_sha256']='different'
    previous={'classifier_version':'shadow-4','comparisons':[original]}
    report={'comparisons':[current,modified]}
    compare_previous_report(report,previous)
    assert report['previous_comparison']['comparable_payloads']==1
    assert report['previous_comparison']['resolved_review_payloads']==1
    assert report['previous_comparison']['new_or_modified_payloads']==1
    assert report['previous_comparison']['changed_payloads']==1
    assert 'previous_tracks' not in modified
    assert previous['comparisons'][0]['review_tracks']==['computer_science']
