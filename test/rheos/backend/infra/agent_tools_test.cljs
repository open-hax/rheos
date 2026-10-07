(ns rheos.backend.infra.agent-tools-test
  "The tool layer's refusal contract, as a caller experiences it.

   `eta-mu kanban status-update` dispatches `kanban_update_status`, so this is
   the surface that accepted `in_review` for three cards. A refusal here has to
   be observable two ways: the card file is unchanged, and the failure carries a
   `:kind` the CLI maps to a non-zero exit — a tool that refused but exited 0
   would leave every scripted caller believing the move landed."
  (:require ["node:fs/promises" :as fsp]
            ["node:os" :as os]
            ["node:path" :as path]
            [cljs.test :refer [deftest testing is]]
            [rheos.backend.infra.agent-tools :as agent-tools]
            [rheos.backend.infra.cli :as cli]
            [rheos.backend.infra.frontmatter-fixture :as frontmatter-fixture]
            [rheos.backend.infra.projects :as projects]))

(defn- tmp-dir []
  (path/join (.tmpdir os) (str "rheos-agent-tools-test-" (.now js/Date) "-" (rand-int 100000))))

(defn- write-task! [dir uuid status]
  (.writeFile fsp (path/join dir (str uuid ".md"))
              (str "---\n"
                   "uuid: \"" uuid "\"\n"
                   "title: \"Task One\"\n"
                   "status: \"" status "\"\n"
                   "priority: \"P3\"\n"
                   "---\n\n# Task One\n\nBody")
              "utf8"))

(defn- ^:async dispatch-outcome
  "Dispatch `tool` against a temp board holding one card at `status`.
   Returns {:error <ex-data or nil> :result :before :after}."
  [status tool args]
  (let [dir (tmp-dir)
        _ (await (.mkdir fsp dir #js {:recursive true}))
        _ (await (write-task! dir "t1" status))
        source-path (path/join dir "t1.md")
        saved {:projects (projects/all) :default-project-id (projects/default-id)}
        before (await (.readFile fsp source-path "utf8"))]
    (projects/set-projects!
     {:projects [{:id "test" :title "Test" :tasks-dir dir :fsm "promethean" :meta {}}]
      :default-project-id "test"})
    (try
      (let [outcome (try
                      {:result (await (agent-tools/dispatch tool args))}
                      (catch :default e
                        {:error (ex-data e) :message (ex-message e)}))]
        (merge outcome {:before before
                        :after (await (.readFile fsp source-path "utf8"))}))
      (finally
        (projects/set-projects! saved)
        (await (.rm fsp dir #js {:recursive true :force true}))))))

(deftest ^:async update-status-refuses-a-non-fsm-status
  (testing "`in_review` is not an FSM state — the tool must refuse it, not write it"
    (let [{:keys [error message result before after]}
          (await (dispatch-outcome "review" "kanban_update_status"
                                   {:uuid "t1" :status "in_review" :project "test"}))]
      (is (nil? result) "the tool must not report success")
      (is (some? error) "it must throw")
      (is (= :refused (:kind error)))
      (is (re-find #"transition rejected" (str message)))
      (is (= before after) "and the card file is byte-identical"))))

(deftest ^:async update-status-refuses-a-missing-edge
  (testing "both states real, edge absent — same refusal, same silence on disk"
    (let [{:keys [error result before after]}
          (await (dispatch-outcome "breakdown" "kanban_update_status"
                                   {:uuid "t1" :status "done" :project "test"}))]
      (is (nil? result))
      (is (= :refused (:kind error)))
      (is (= before after)))))

(deftest ^:async update-status-writes-on-a-legal-move
  (testing "the refusal tests above would pass on a tool that never writes"
    (let [{:keys [error result before after]}
          (await (dispatch-outcome "breakdown" "kanban_update_status"
                                   {:uuid "t1" :status "ready" :project "test"}))]
      (is (nil? error))
      (is (:ok result))
      (is (= "breakdown" (:from result)))
      (is (= "ready" (:to result)))
      (is (not= before after))
      (is (re-find #"status: \"ready\"" after)))))

;; ---------------------------------------------------------------------------
;; The exit code a scripted caller actually observes
;; ---------------------------------------------------------------------------

(defn- ^:async run-cli!
  "Drive [[cli/main]] end to end against a temp board holding one card at
   `status`, and return the exit code it left on the process.

   `main` reads `process.argv` and writes `process.exitCode` — the only way to
   prove a refusal reaches a caller as a non-zero exit is to go through both.
   Both globals are restored, and `exitCode` is reset to 0, or a passing suite
   would inherit this test's failure code."
  [status argv-tail]
  (let [dir (tmp-dir)
        _ (await (.mkdir fsp dir #js {:recursive true}))
        _ (await (write-task! dir "t1" status))
        config-path (path/join dir "board.edn")
        _ (await (.writeFile fsp config-path
                             (str "{:tasks-dir \"" dir "\" :fsm :promethean}") "utf8"))
        saved-argv js/process.argv
        saved-projects {:projects (projects/all) :default-project-id (projects/default-id)}]
    (set! (.-exitCode js/process) 0)
    (set! (.-argv js/process)
          (clj->js (concat ["node" "rheos"] argv-tail ["--config" config-path])))
    (try
      (await (cli/main))
      {:exit-code (.-exitCode js/process)
       :after (await (.readFile fsp (path/join dir "t1.md") "utf8"))}
      (finally
        (set! (.-argv js/process) saved-argv)
        (set! (.-exitCode js/process) 0)
        (projects/set-projects! saved-projects)
        (await (.rm fsp dir #js {:recursive true :force true}))))))

(deftest ^:async status-update-exits-non-zero-on-a-refusal
  (testing "a refused move reaches the caller as exit 3, not a silent success"
    (let [{:keys [exit-code after]}
          (await (run-cli! "review" ["status-update" "t1" "--to" "in_review"]))]
      (is (= 3 exit-code)
          "exit 0 here is indistinguishable from a completed move")
      (is (= (:refused cli/exit-codes) exit-code)
          "and it is the published `:refused` code, not an incidental non-zero")
      (is (re-find #"status: \"review\"" after)
          "the card still holds its real status"))))

(deftest ^:async status-update-exits-zero-on-a-legal-move
  (testing "the exit assertion above would pass on a CLI that always failed"
    (let [{:keys [exit-code after]}
          (await (run-cli! "breakdown" ["status-update" "t1" "--to" "ready"]))]
      (is (= 0 exit-code))
      (is (re-find #"status: \"ready\"" after)))))

(deftest exit-codes-cover-refusal
  (testing "the published mapping the tests above depend on"
    (is (= 3 (:refused cli/exit-codes)))
    (is (pos? (:refused cli/exit-codes)))))

;; Real frontmatter tool/CLI writes share the existing policy and ledger path.
(defn- ^:async frontmatter-outcome! [{:keys [task project]} updates]
  (try
    {:result (await (agent-tools/dispatch
                     "kanban_update_frontmatter"
                     {:uuid (:uuid task) :project (:id project) :updates updates}))}
    (catch :default e
      {:error (ex-data e) :message (ex-message e)})))

(defn- ^:async exercise-tool-mutations! [board changes]
  (doseq [[key value] changes]
    (let [before (await (frontmatter-fixture/snapshot board))
          {:keys [result error]} (await (frontmatter-outcome! board {key value}))
          readback (await (agent-tools/dispatch
                           "kanban_read_task"
                           {:uuid (get-in board [:task :uuid])
                            :project (get-in board [:project :id])}))
          after (await (frontmatter-fixture/snapshot board))]
      (is (nil? error) "the actual registered tool must accept descriptive metadata")
      (is (true? (:ok result)))
      (is (= value (get-in result [:frontmatter key])))
      (is (= value (get-in readback [:frontmatter key])))
      (is (= (:sections readback) (get-in after [:parsed :sections])))
      (frontmatter-fixture/assert-mutation! before after key value "agent"))))

(deftest ^:async tool-sets-and-replaces-design-with-real-ledger-events
  (await (frontmatter-fixture/with-board!
           #(exercise-tool-mutations!
              % [[:design "docs/designs/not-created-yet.md"]
                 [:design "docs/designs/replacement.md"]]))))

(deftest ^:async tool-retains-existing-descriptive-field-behavior
  (await (frontmatter-fixture/with-board!
           #(exercise-tool-mutations! % [[:title "Changed title"] [:priority "P1"]]))))

(defn- ^:async exercise-tool-refusals! [board]
  (doseq [key frontmatter-fixture/protected-keys
          updates (frontmatter-fixture/mixed-updates key)]
    (let [before (await (frontmatter-fixture/snapshot board))
          {:keys [result error]} (await (frontmatter-outcome! board updates))
          after (await (frontmatter-fixture/snapshot board))]
      (is (nil? result))
      (is (= :usage (:kind error)))
      (is (some #{(name key)} (:keys error)))
      (frontmatter-fixture/assert-unchanged! before after)))
  (doseq [updates (frontmatter-fixture/mixed-updates :status)]
    (let [before (await (frontmatter-fixture/snapshot board))
          {:keys [error message]} (await (frontmatter-outcome! board updates))
          after (await (frontmatter-fixture/snapshot board))]
      (is (= :usage (:kind error)))
      (is (= "status" (:key error)))
      (is (re-find #"FSM-governed" (str message)))
      (frontmatter-fixture/assert-unchanged! before after)))
  (let [before (await (frontmatter-fixture/snapshot board))
        {:keys [error message]} (await (frontmatter-outcome! board {}))
        after (await (frontmatter-fixture/snapshot board))]
    (is (= :usage (:kind error)))
    (is (= "no frontmatter updates given" message))
    (frontmatter-fixture/assert-unchanged! before after)))

(deftest ^:async tool-refuses-entire-mixed-or-empty-update
  (await (frontmatter-fixture/with-board! exercise-tool-refusals!)))

(defn- ^:async frontmatter-cli! [{:keys [task config-path]} pairs]
  (let [saved-argv (.-argv js/process)
        saved-exit (.-exitCode js/process)
        saved-projects {:projects (projects/all) :default-project-id (projects/default-id)}]
    (try
      (set! (.-exitCode js/process) 0)
      (set! (.-argv js/process)
            (clj->js (concat ["node" "rheos" "frontmatter" (:uuid task)]
                            (mapcat (fn [[key value]] ["--set" (str (name key) "=" value)]) pairs)
                            ["--config" config-path])))
      (await (cli/main))
      (.-exitCode js/process)
      (finally
        (set! (.-argv js/process) saved-argv)
        (set! (.-exitCode js/process) saved-exit)
        (projects/set-projects! saved-projects)))))

(defn- ^:async exercise-cli-mutations! [board changes]
  (doseq [[key value] changes]
    (let [before (await (frontmatter-fixture/snapshot board))
          exit-code (await (frontmatter-cli! board [[key value]]))
          after (await (frontmatter-fixture/snapshot board))]
      (is (= 0 exit-code) "actual argv/main path must report successful design mutation")
      (frontmatter-fixture/assert-mutation! before after key value "cli"))))

(deftest ^:async cli-sets-and-replaces-design-with-real-ledger-events
  (await (frontmatter-fixture/with-board!
           #(exercise-cli-mutations!
              % [[:design "docs/designs/not-created-yet.md"]
                 [:design "docs/designs/replacement.md"]]))))

(deftest ^:async cli-retains-existing-descriptive-field-behavior
  (await (frontmatter-fixture/with-board!
           #(exercise-cli-mutations! % [[:title "Changed title"] [:priority "P1"]]))))

(defn- ^:async exercise-cli-refusals! [board]
  (doseq [pairs (concat [[]]
                       (for [key (conj frontmatter-fixture/protected-keys :status)
                             updates (frontmatter-fixture/mixed-updates key)]
                         (vec updates)))]
    (let [before (await (frontmatter-fixture/snapshot board))
          exit-code (await (frontmatter-cli! board pairs))
          after (await (frontmatter-fixture/snapshot board))]
      (is (= (:usage cli/exit-codes) exit-code))
      (frontmatter-fixture/assert-unchanged! before after))))

(deftest ^:async cli-refuses-entire-mixed-update-and-missing-set
  (await (frontmatter-fixture/with-board! exercise-cli-refusals!)))
