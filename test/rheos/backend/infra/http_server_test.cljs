(ns rheos.backend.infra.http-server-test
  "Production frontmatter handler and real JSON/writer/ledger boundary.

   Fastify injection does not listen on a socket or boot the server, watchers
   or MCP transport. No policy or filesystem writer is replaced."
  (:require ["fastify" :default Fastify]
            [cljs.test :refer [deftest is]]
            [rheos.backend.infra.frontmatter-fixture :as fixture]
            [rheos.backend.infra.http-server :as http]))

(defn- ^:async with-http! [board f]
  (let [app (Fastify #js {:logger false})]
    (try
      (.patch app "/api/task/:uuid/frontmatter" http/handle-update-frontmatter)
      (await (f board app))
      (finally
        (await (.close app))))))

(defn- ^:async patch! [{:keys [task project]} ^js app body]
  (let [response (await (.inject app
                                #js {:method "PATCH"
                                     :url (str "/api/task/" (:uuid task)
                                               "/frontmatter?project=" (:id project))
                                     :payload (clj->js body)}))]
    {:status (.-statusCode response)
     :body (js->clj (.json response) :keywordize-keys true)}))

(defn- ^:async exercise-mutations! [board app changes]
  (doseq [[key value body] changes]
    (let [before (await (fixture/snapshot board))
          response (await (patch! board app body))
          after (await (fixture/snapshot board))]
      (is (= 200 (:status response)))
      (is (= value (get-in response [:body :frontmatter key])))
      (is (= (get-in after [:parsed :sections]) (get-in response [:body :sections])))
      (fixture/assert-mutation! before after key value "web"))))

(deftest ^:async patch-sets-and-replaces-design-through-both-body-shapes
  (await (fixture/with-board!
           (fn [board]
             (with-http!
               board
               (fn [fixture app]
                 (exercise-mutations!
                   fixture app
                   [[:design "docs/designs/not-created-yet.md"
                     {:updates {"design" "docs/designs/not-created-yet.md"}}]
                    [:design "docs/designs/replacement.md"
                     {:key "design" :value "docs/designs/replacement.md"}]])))))))

(deftest ^:async patch-retains-existing-descriptive-field-behavior
  (await (fixture/with-board!
           (fn [board]
             (with-http!
               board
               (fn [fixture app]
                 (exercise-mutations!
                   fixture app
                   [[:title "Changed title" {:updates {:title "Changed title"}}]
                    [:priority "P1" {:key "priority" :value "P1"}]])))))))

(defn- ^:async exercise-refusals! [board app]
  (doseq [key fixture/protected-keys
          updates (fixture/mixed-updates key)]
    (let [before (await (fixture/snapshot board))
          response (await (patch! board app {:updates updates}))
          after (await (fixture/snapshot board))]
      (is (= 400 (:status response)))
      (is (re-find #"frontmatter keys not allowed" (str (get-in response [:body :error]))))
      (fixture/assert-unchanged! before after)))
  (doseq [updates (fixture/mixed-updates :status)]
    (let [before (await (fixture/snapshot board))
          response (await (patch! board app {:updates updates}))
          after (await (fixture/snapshot board))]
      (is (= 400 (:status response)))
      (is (= (str "status is not editable via frontmatter; POST /api/task/"
                  (get-in board [:task :uuid]) "/status")
             (get-in response [:body :error])))
      (fixture/assert-unchanged! before after)))
  (doseq [body [{} {:updates {}}]]
    (let [before (await (fixture/snapshot board))
          response (await (patch! board app body))
          after (await (fixture/snapshot board))]
      (is (= 400 (:status response)))
      (is (= "missing key or updates" (get-in response [:body :error])))
      (fixture/assert-unchanged! before after))))

(deftest ^:async patch-refuses-entire-mixed-or-empty-update
  (await (fixture/with-board! #(with-http! % exercise-refusals!))))
