--!strict
--[[
	MonetizationService.luau

	Robux in, Gems/items out.

	Receipt handling is the one place in the game where getting it wrong costs
	real money, so the rules are strict:

	  * ProcessReceipt returns NotProcessedYet on ANY failure path, including a
	    player who has left. Roblox will re-deliver the receipt later. Granting
	    optimistically and returning PurchaseGranted on a failed save is how
	    players lose paid currency.
	  * Every receipt id is recorded on the profile before we return
	    PurchaseGranted, and re-delivery of a recorded id is a no-op grant. That
	    makes the grant idempotent against Roblox's at-least-once delivery.
	  * A product with an unconfigured (0) asset id is refused outright rather
	    than matched by accident.
]]

local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")

local Shared = game:GetService("ReplicatedStorage"):WaitForChild("Shared")
local Monetization = require(Shared.Config.Monetization)
local Types = require(Shared.Types)

local CurrencyService = require(script.Parent.CurrencyService)
local DataService = require(script.Parent.DataService)
local SyncService = require(script.Parent.SyncService)

type Profile = Types.Profile

local MonetizationService = {}

-- Receipt ids live on the profile so the record survives a server hop.
local RECEIPT_KEY = "ProcessedReceipts"

--------------------------------------------------------------------------------
-- Game passes
--------------------------------------------------------------------------------

local function refreshPasses(player: Player, profile: Profile)
	local changed = false

	for key, pass in Monetization.GamePasses do
		if pass.Id == 0 then
			continue
		end
		local ok, owns = pcall(function()
			return MarketplaceService:UserOwnsGamePassAsync(player.UserId, pass.Id)
		end)
		if ok and owns and not profile.Passes[key] then
			profile.Passes[key] = true
			changed = true
		end
	end

	if changed then
		DataService.markDirty(player)
		SyncService.push(player)
	end
end

--------------------------------------------------------------------------------
-- Grants
--------------------------------------------------------------------------------

local function grantProduct(player: Player, profile: Profile, product: Monetization.DevProduct)
	if product.Gems then
		CurrencyService.addGems(player, profile, product.Gems)
	end
	if product.Gold then
		CurrencyService.addGold(player, profile, product.Gold)
	end
	if product.Items then
		CurrencyService.addItems(player, profile, product.Items)
	end
	SyncService.push(player)
	SyncService.toast(player, "success", `Purchased {product.Display}!`)
end

--------------------------------------------------------------------------------
-- Receipt processing
--------------------------------------------------------------------------------

local function processReceipt(receiptInfo: {
	PlayerId: number,
	ProductId: number,
	PurchaseId: string,
	CurrencySpent: number,
}): Enum.ProductPurchaseDecision
	local product = Monetization.productByAssetId(receiptInfo.ProductId)
	if not product then
		-- An unknown product id is a configuration bug, not a player problem.
		-- Leave it pending so it can be granted after the config is fixed.
		warn(`[Monetization] receipt for unconfigured product id {receiptInfo.ProductId}`)
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local player = Players:GetPlayerByUserId(receiptInfo.PlayerId)
	if not player then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local profile = DataService.get(player)
	if not profile then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local receipts = (profile :: any)[RECEIPT_KEY]
	if type(receipts) ~= "table" then
		receipts = {}
		;(profile :: any)[RECEIPT_KEY] = receipts
	end

	-- Idempotency: Roblox may deliver the same PurchaseId more than once.
	if receipts[receiptInfo.PurchaseId] then
		return Enum.ProductPurchaseDecision.PurchaseGranted
	end

	local ok, err = pcall(grantProduct, player, profile, product)
	if not ok then
		warn(`[Monetization] grant failed for {player.Name} / {product.Key}: {err}`)
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	receipts[receiptInfo.PurchaseId] = os.time()

	-- Only confirm the purchase once the grant is safely on disk. If the save
	-- fails, Roblox re-delivers and the idempotency check above prevents a
	-- double grant.
	if not DataService.flush(player, false) then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	return Enum.ProductPurchaseDecision.PurchaseGranted
end

--------------------------------------------------------------------------------
-- Prompts
--------------------------------------------------------------------------------

function MonetizationService.prompt(player: Player, productKey: string): Types.Result<nil>
	local product = Monetization.DevProducts[productKey]
	if product then
		if product.Id == 0 then
			return { ok = false, err = "This product is not available yet." }
		end
		local ok = pcall(function()
			MarketplaceService:PromptProductPurchase(player, product.Id)
		end)
		return if ok then { ok = true } else { ok = false, err = "Could not open the purchase prompt." }
	end

	local pass = Monetization.GamePasses[productKey]
	if pass then
		if pass.Id == 0 then
			return { ok = false, err = "This pass is not available yet." }
		end
		local ok = pcall(function()
			MarketplaceService:PromptGamePassPurchase(player, pass.Id)
		end)
		return if ok then { ok = true } else { ok = false, err = "Could not open the purchase prompt." }
	end

	return { ok = false, err = "Unknown product." }
end

--------------------------------------------------------------------------------
-- Lifecycle
--------------------------------------------------------------------------------

function MonetizationService.start()
	MarketplaceService.ProcessReceipt = processReceipt

	DataService.onLoaded(function(player, profile)
		task.spawn(refreshPasses, player, profile)
	end)

	-- A pass bought mid-session should apply without a rejoin.
	MarketplaceService.PromptGamePassPurchaseFinished:Connect(function(player, passId, wasPurchased)
		if not wasPurchased then
			return
		end
		local profile = DataService.get(player)
		if not profile then
			return
		end
		for key, pass in Monetization.GamePasses do
			if pass.Id == passId and passId ~= 0 then
				profile.Passes[key] = true
				DataService.markDirty(player)
				SyncService.push(player)
				SyncService.toast(player, "success", `{pass.Display} activated!`)
				break
			end
		end
	end)
end

return MonetizationService
