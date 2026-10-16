"""Execute the actual EA init/deinit bodies with a deterministic terminal API fake.

This checks bridge lifecycle decisions, not Wine/MQL5 API compatibility (the real
MetaEditor build checks that separately). No terminal, credentials or orders are used.
"""
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class BridgeLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang++') or shutil.which('g++')
        if not compiler:
            raise unittest.SkipTest('A C++ compiler is required for the EA lifecycle harness')
        source = (Path(__file__).resolve().parents[1] / 'mt5/PredictionBridge.mq5').read_text()
        # These adjacent, C++-compatible MQL5 bodies are compiled verbatim.
        bodies = source[source.index('int OnInit()'):source.index('void OnTimer()')]
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        harness = Path(cls.tmp.name) / 'lifecycle.cpp'
        cls.binary = Path(cls.tmp.name) / 'lifecycle'
        harness.write_text(r'''
#include <iostream>
#include <string>
#include <algorithm>
using string = std::string;
const int INVALID_HANDLE=-1, FILE_READ=1, FILE_WRITE=2, FILE_BIN=4;
const int INIT_SUCCEEDED=0, INIT_FAILED=1, INIT_PARAMETERS_INCORRECT=2, MQL_TESTER=3;
const string STATE_DIR="PredictionBridge", LOCK_NAME="PredictionBridge.v1.executor";
int file_owner=-1, next_handle=1;
bool global_exists=false, create_existing_ok=false, fail_release=false;
double global_value=0;
int StringLen(string s) { return s.size(); }
int StringFind(string s,string part) { auto p=s.find(part); return p==string::npos?-1:int(p); }
string StringSubstr(string s,int start) { return s.substr(start); }
long StringToInteger(string s) { return std::stol(s); }
bool DigitsOnly(string s) { return !s.empty() && std::all_of(s.begin(),s.end(),[](char c){return c>='0' && c<='9';}); }
bool ValidBrokerSymbol(string s,string base) { return s==base+".sml"; }
bool MQLInfoInteger(int) { return false; }
template<typename... Args> void Print(Args...) {}
int FileOpen(string,int) { if(file_owner!=-1) return -1; return file_owner=next_handle++; }
void FileClose(int h) { if(h==file_owner) file_owner=-1; }
bool GlobalVariableCheck(string) { return global_exists; }
bool GlobalVariableTemp(string) {
    if(global_exists) return create_existing_ok;
    global_exists=true; global_value=0; return true;
}
long GlobalVariableSet(string,double value) { global_exists=true; global_value=value; return 1; }
bool GlobalVariableSetOnCondition(string,double value,double expected) {
    if(!global_exists || global_value!=expected || (fail_release && value==0)) return false;
    global_value=value; return true;
}
bool SymbolSelect(string,bool) { return true; }
struct Bridge {
    string CoordinatorURL="http://127.0.0.1:8787", LocalToken=string(48,'x');
    long ExpectedLogin=123456;
    string ExpectedServer="OANDA_Global-Demo-1", EURUSDSymbol="EURUSD.sml", XAUUSDSymbol="XAUUSD.sml";
    bool EnableOrders=false, owns_lock=false, halted=false, pending_ok=true, timer=false;
    int PollSeconds=2, MaxTickAgeSeconds=5, lock_handle=-1;
    string pending="", Symbols[2];
    unsigned long submitted_at=0;
    bool LoadPending() { return pending_ok; }
    bool EventSetTimer(int) { timer=true; return true; }
    void EventKillTimer() { timer=false; }
''' + bodies + r'''
};
void require(bool ok,const char *message) {
    if(!ok) { std::cerr<<message<<"\n"; std::exit(1); }
}
int main(int argc,char **argv) {
    string scenario=argv[1]; Bridge first;
    if(scenario=="orphan") {
        global_exists=true; global_value=1; create_existing_ok=true;
        require(first.OnInit()==0,"An orphaned flag must recover only after obtaining exclusive file ownership");
    } else if(scenario=="duplicate") {
        require(first.OnInit()==0,"First bridge should start");
        Bridge second;
        require(second.OnInit()!=0,"Second chart must not start while the first owns the executor");
        second.OnDeinit(8);
        Bridge third;
        require(third.OnInit()!=0,"Failed second chart must not release the first chart's ownership");
        third.OnDeinit(8);
        first.OnDeinit(1);
        create_existing_ok=true;
        require(second.OnInit()==0,"A new chart should start after the owner exits");
        second.OnDeinit(1);
    } else if(scenario=="pending_failure") {
        first.pending_ok=false;
        require(first.OnInit()!=0,"Unreadable pending acknowledgement must block initialization");
        first.OnDeinit(8);
        first.pending_ok=true; create_existing_ok=true;
        require(first.OnInit()==0,"Cleanup after failed init must allow a later clean start");
    } else {
        require(first.OnInit()==0,"Initial bridge should start");
        fail_release=scenario=="release_failure";
        first.OnDeinit(5);
        fail_release=false;
        create_existing_ok=scenario=="release_failure";
        first.EnableOrders=true;
        require(first.OnInit()==0,"Changing inputs must restart the existing bridge without a terminal restart");
        first.OnDeinit(5);
        require(!first.owns_lock && first.lock_handle==INVALID_HANDLE,"Deinit must clear local ownership before future initialization failures");
    }
    return 0;
}
''')
        flags = []
        if sys.platform == 'darwin':
            # Match the selected compiler's SDK instead of an unrelated CLT SDK.
            sdk = subprocess.run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'],
                                 capture_output=True, text=True, check=True, timeout=10)
            flags = ['-isysroot', sdk.stdout.strip()]
        built = subprocess.run([compiler, *flags, '-std=c++17', str(harness), '-o', str(cls.binary)],
                               capture_output=True, text=True, timeout=30)
        if built.returncode:
            raise AssertionError('Lifecycle harness compilation failed:\n' + built.stderr)

    def check_scenario(self, scenario):
        result = subprocess.run([str(self.binary), scenario], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_input_change_reuses_existing_temporary_variable(self):
        self.check_scenario('input_change')

    def test_orphaned_flag_recovers_after_exclusive_file_acquisition(self):
        self.check_scenario('orphan')

    def test_second_chart_cannot_start_or_release_first_chart(self):
        self.check_scenario('duplicate')

    def test_failed_pending_load_releases_executor_for_retry(self):
        self.check_scenario('pending_failure')

    def test_release_failure_does_not_leave_restart_permanently_blocked(self):
        self.check_scenario('release_failure')
