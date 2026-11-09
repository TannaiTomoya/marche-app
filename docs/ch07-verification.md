# 07章の検証記録（2026-11-09）

## 認可ガード進捗

- [x] 既存の権限仕様を読み、docs/authorization.md に集約
- [x] 確認画面の権限をユーザーに確認（本人・管理者）。中断・取消は提供された07章教材の明示仕様を使用
- [x] 権限表と、サーバー側のログイン・所有者チェックを確認
- [x] 取消のPOST・CSRF、pendingのみ、Session失効後の取消を確認
- [x] 拒否テストと許可テストを追加
- [x] 判定を一時的に外して失敗を検出し、元に戻して成功を確認
- [x] 独立したCodexレビュー役でレビュー（高・中の指摘なし）

## コマンドと結果

実行場所は専用の作業コピー。既存のインストール済み環境を使用した。

```sh
export UV_PROJECT_ENVIRONMENT=/Users/tannaitomoya/camp/200_python/marche-app/.venv
export UV_CACHE_DIR=/private/tmp/marche-uv-cache
uv run --no-sync ruff format --check .
uv run --no-sync ruff check .
uv run --no-sync pytest -q
```

整形・静的検査成功。最終結果 `112 passed in 22.74s`。
CIも `.github/workflows/ci.yml` でRuffとpytestを実行する。

| 一時的に外した判定 | 対象テスト | 失敗の証拠 |
|---|---|---|
| orders.get_own_order_or_403 の所有者判定 | `tests/test_payment.py -k 未ログインと他人` | 3 failed, 3 passed |
| completeのlogin_required | 同上 | 1 failed, 5 passed |
| cancelのlogin_required | 同上 | 2 failed, 4 passed |
| inventory.cancelのpending制限 | `tests/test_payment.py -k 支払い待ち以外` | 1 failed, 1 passed |

全ての変更をfinallyで復元してから最終テストを実行した。判定を外したコードはコミットしない。

## 追加テストの内容

- Checkout作成に失敗したときの注文取消、カート保持、在庫予約解除
- 本人・管理者の確認画面、中断画面、取消POSTの許可
- 未ログイン・他人・存在しない注文の拒否（注文とSessionを変更しない）
- GET表示での状態不変、Session失効失敗時のpending維持、paid/cancelledの変更禁止
- 取消POSTのCSRF拒否と、画面から取得したトークンでの成功
- expire時点ではまだpendingであることと、取消後の在庫予約解除
- 保存済み明細のJPY単価、数量、商品名、metadata、メール、31分期限、絶対URL
- Stripe SDKのcreate/retrieve/expireをフェイクで検証、例外変換、キー未設定

## 実サービスで残る確認

Stripeのテストキー設定、テストカード決済、Stripe画面とダッシュボードのスクリーンショットは本人が実施する。
手順は `docs/ch07-manual-check.md`。自動テストの成功を実決済の確認済みとして扱わない。

## 参考

- ユーザー提供の「07. Stripe Checkout（平日課題）」本文
- https://docs.stripe.com/api/checkout/sessions/create?lang=python
- https://docs.stripe.com/currencies#zero-decimal
