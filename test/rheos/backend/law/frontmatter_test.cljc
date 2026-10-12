(ns rheos.backend.law.frontmatter-test
  (:require #?(:clj [clojure.test :refer [deftest is testing]]
               :cljs [cljs.test :refer [deftest is testing]])
            [rheos.backend.law.frontmatter :as frontmatter]))

(deftest design-is-descriptive-metadata
  (testing "an unverified design path is admitted by the existing key policy"
    (is (true? (frontmatter/mutable-key? :design)))
    (is (empty? (frontmatter/disallowed-keys
                 {:design "docs/designs/not-created-yet.md"}))))
  (testing "design can be supplied alongside existing descriptive fields"
    (is (empty? (frontmatter/disallowed-keys
                 {:design "docs/designs/replacement.md" :title "Updated" :priority "P1"}))))
  (testing "the existing descriptive keys remain admitted"
    (doseq [key [:title :priority :labels :points :category :description :estimate :assignee]]
      (is (true? (frontmatter/mutable-key? key))))))

(deftest protected-and-unknown-keys-remain-closed
  (doseq [key [:write-id :write_id :source-path :sourcePath :source
              :uuid :created-at :created_at :unknown-field]]
    (is (false? (frontmatter/mutable-key? key)))
    (is (= [key] (frontmatter/disallowed-keys {key "forbidden"}))))
  (is (= #{:uuid :unknown-field}
         (set (frontmatter/disallowed-keys
                {:title "Allowed" :uuid "forbidden" :unknown-field "forbidden"})))))

(deftest status-keeps-its-dedicated-fsm-route
  (is (false? (frontmatter/mutable-key? :status)))
  (is (true? (frontmatter/status-update? {:status "ready"})))
  (is (empty? (frontmatter/disallowed-keys {:status "ready"})))
  (is (false? (frontmatter/status-update? {:title "Allowed"}))))

(deftest empty-update-is-neutral-at-the-key-law
  (is (empty? (frontmatter/disallowed-keys {})))
  (is (false? (frontmatter/status-update? {}))))
