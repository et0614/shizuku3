# リリース手順

リリースは GitHub Actions（`.github/workflows/release.yml`）で自動作成される。
`v*` タグを push すると、以下が順に実行される。

1. **build**（Ubuntu）: `tools/make_release.py` で2つの zip を作成
   - `shizuku3-v<版>-win-x64.zip`（Windows）
   - `shizuku3-v<版>-osx-arm64.zip`（Apple Silicon Mac。実行権限付き）
2. **smoke-test**（Windows / macOS）: 各 zip を展開してエミュレータを起動し、
   BACnet での読み取り・30分ステップ・リセット、GUI のページ応答を確認（`tools/smoke_test.py`）
3. **release**: テストが両方通った場合のみ、zip を添付した**下書き（draft）**の Release を作成

## 手順

1. 変更をすべてコミットして `main` に push する。
2. （任意）Actions タブ → **Release** → **Run workflow** で事前確認する。
   タグなしで実行するので Release は作られず、ビルドとテストだけが走る。
3. タグを付けて push する。

   ```
   git tag v0.2.1
   git push origin v0.2.1
   ```

4. 数分後、GitHub の Releases に下書きができる。リリースノートを編集する
   （自動で入るのはコミット一覧のみ。日英の変更点・クイックスタートに差し替える）。
5. **Publish release** を押して公開する。

## 失敗したとき

- Actions のログを確認する。smoke-test が失敗した場合は、ログの最後にエミュレータの出力が表示される。
- 修正して push したら、同じ版のタグを付け直す。

  ```
  git tag -d v0.2.1
  git push origin :refs/tags/v0.2.1
  git tag v0.2.1
  git push origin v0.2.1
  ```

  下書きの Release が残っていれば、先に GitHub 上で削除しておく。

## ローカルで zip を作る場合

```
python tools/make_release.py 0.2.1               # dist/ に2つの zip を作成
python tools/make_release.py 0.2.1 --skip-build  # 既存のビルド結果を再利用
```

`--skip-build` は古いビルドが混入するおそれがあるので、配布用には使わない。

## CI で確認できないこと

CI の Mac ではダウンロード扱いにならないため、Gatekeeper の許可の流れ
（「開発元を確認できません」→ システム設定で「このまま開く」）と、
Finder からのダブルクリック操作は確認できない。macOS 版に大きな変更を入れたときは、
Mac 実機で zip をブラウザからダウンロードして一通り試すこと。
