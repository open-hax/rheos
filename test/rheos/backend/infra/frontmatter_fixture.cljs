(ns rheos.backend.infra.frontmatter-fixture
  "Isolated real-file fixtures shared by frontmatter adapter contract tests.

   No policy, parser or writer is substituted. Callers use the canonical
   content parser and EventAdmission query for their assertions."
  (:require ["node:fs/promises" :as fsp]
            ["node:os" :as os]
            ["node:path" :as path]
            [cljs.test :refer [is]]
            [clojure.string :as str]
            [rheos.backend.domain.events :as events]
            [rheos.backend.infra.ledger :as ledger]
            [rheos.backend.infra.projects :as projects]
            [rheos.backend.infra.task-edit :as task-edit]
            [rheos.backend.infra.watcher :as watcher]
            [rheos.backend.shape.content-parser :as content-parser]))

(defn ^:async snapshot [{:keys [dir task]}]
  (let [raw (await (.readFile fsp (:source-path task) "utf8"))]
    {:raw raw
     :parsed (content-parser/parse-task-content raw)
     :ledger (await (.readFile fsp (path/join dir ".events" "ledger.edn") "utf8"))
     :events (await (events/query-events (ledger/get-ledger dir) {}))}))

(defn ^:async with-board! [f]
  (let [dir (await (.mkdtemp fsp (path/join (.tmpdir os) "rheos-frontmatter-")))
        uuid (str (random-uuid))
        project {:id (str "frontmatter-" uuid) :title "Frontmatter test"
                 :tasks-dir dir :fsm "promethean" :meta {}}
        task {:uuid uuid :source-path (path/join dir (str uuid ".md"))}
        config-path (path/join dir "board.edn")
        saved {:projects (projects/all) :default-project-id (projects/default-id)}
        fixture {:dir dir :task task :project project :config-path config-path}]
    (try
      (await (.writeFile fsp (:source-path task)
                        (str "---\nuuid: \"" uuid "\"\n"
                             "title: \"Design-bearing card\"\nstatus: \"incoming\"\n"
                             "priority: \"P3\"\ncreated_at: \"2026-10-01T00:00:00Z\"\n"
                             "description: \"Keep this metadata\"\nlabels: \"review, design\"\n"
                             "---\n\n# Design-bearing card\n\nKeep **this body** intact.\n")
                        "utf8"))
      (await (.writeFile fsp config-path
                        (pr-str {:projects [project] :default-project-id (:id project)})
                        "utf8"))
      (projects/set-projects! {:projects [project] :default-project-id (:id project)})
      ;; Seed the prefix through the real writer, including a real comment event.
      (await (task-edit/append-comment!
               {:project project :task task :text "Keep this existing comment."
                :source "frontmatter-fixture"}))
      (await (f fixture))
      (finally
        (projects/set-projects! saved)
        (swap! ledger/ledger-cache dissoc dir)
        (swap! watcher/pending-writes
               (fn [pending]
                 (into {} (remove (fn [[_ value]] (= uuid (:task-id value)))) pending)))
        (await (.rm fsp dir #js {:recursive true :force true}))))))

(defn assert-mutation! [before after key value source]
  (let [old-fm (get-in before [:parsed :frontmatter])
        new-fm (get-in after [:parsed :frontmatter])
        appended (vec (drop (count (:events before)) (:events after)))
        payload (:payload (first appended))]
    (is (= value (get new-fm key)))
    (is (= (dissoc old-fm key :write-id) (dissoc new-fm key :write-id))
        "all unrelated supported frontmatter survives")
    (is (= (get-in before [:parsed :sections]) (get-in after [:parsed :sections]))
        "body and comment sections survive canonical serialization")
    (is (string? (:write-id new-fm)))
    (is (seq (:write-id new-fm)))
    (is (not= (:write-id old-fm) (:write-id new-fm)))
    (is (str/starts-with? (:ledger after) (:ledger before))
        "all pre-existing event bytes are an unchanged prefix")
    (is (= 1 (count appended)) "exactly one canonical event per supplied key")
    (is (= "frontmatter" (:type payload)))
    (is (= (name key) (:key payload)))
    (is (= (get old-fm key) (:old-value payload)))
    (is (= value (:new-value payload)))
    (is (= (:uuid old-fm) (:task-id payload)))
    (is (= source (:source payload)))
    (is (= (:write-id new-fm) (:write-id payload)))))

(defn assert-unchanged! [before after]
  (is (= (:raw before) (:raw after)) "a refusal preserves every card byte")
  (is (= (:ledger before) (:ledger after)) "a refusal preserves every ledger byte")
  (is (= (:events before) (:events after)) "no changed-key event is admitted"))

(def protected-keys
  [:uuid :write-id :write_id :source-path :sourcePath :source
   :created-at :created_at :unknown-field])

(defn mixed-updates [key]
  [(array-map :design "docs/designs/must-not-land.md" key "forbidden")
   (array-map key "forbidden" :design "docs/designs/must-not-land.md")])
