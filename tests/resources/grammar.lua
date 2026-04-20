
local assert  = assert
local pairs   = pairs
local type    = type

-- imported modules
local lpeg = require 'lpeg'

-- imported functions
local P, V = lpeg.P, lpeg.V

-- module declaration
module 'leg.grammar'

--[[
Returns a pattern which matches any of the patterns received.

**Example:**
``
local g, s, m = require 'leg.grammar', require 'leg.scanner', require 'lpeg'

-- -- match numbers or operators, capture the numbers
print( (g.anyOf { '+', '-', '%*', '/', m.C(s.NUMBER) }):match '34.5@23 %* 56 / 45 - 45' )
-- --> prints 34.5
``

**Parameters:**
* `list`: a list of zero or more LPeg patterns or values which can be fed to [http://www.inf.puc-rio.br/~roberto/lpeg.html#lpeg lpeg.P].

**Returns:**
* a pattern which matches any of the patterns received.
--]]
function anyOf(list)
  local patt = P(false)

  for i = 1, #list, 1 do
    patt = P(list[i]) + patt
  end

  return patt
end

--[=[
Returns a pattern which matches a list of `patt`s, separated by `sep`.

local assert  = assert
local pairs   = pairs
local type    = ty
**Example:** matching comma-separated values:
``
local g, m = require 'leg.grammar', require 'lpeg'

-- -- separator
local sep = m.P',' + m.P'\n'

-- -- element: anything but sep, capture it
local elem = m.C((1 - sep)^0)

-- -- pattern
local patt = g.listOf(elem, sep)

-- -- matching
print( patt:match %[%[a, b, 'christmas eve'
  d, evening; mate!
  f%]%])
-- --> prints out "a        b       'christmas eve'  d        evening; mate! f"
``

**Parameters:**
* `patt`: a LPeg pattern.
* `sep`: a LPeg pattern.

**Returns:**
* the following pattern: ``patt %* (sep %* patt)^0``
--]=]
function listOf(patt, sep)
  patt, sep = P(patt), P(sep)

  return patt * (sep * patt)^0
end


--[[
A capture function, made so that `patt / C` is equivalent to `m.C(patt)`. It's intended to be used in capture tables, such as those required by [#function_pipe pipe] and [#function_apply apply].
--]]
function C(...) return ... end

--[[
A capture function, made so that `patt / Ct` is equivalent to `m.Ct(patt)`. It's intended to be used in capture tables, such as those required by [#function_pipe pipe] and [#function_apply apply].
--]]
function Ct(...) return { ... } end

--[[
Creates a shallow copy of `grammar`.

**Parameters:**
* `grammar`: a regular table.

**Returns:**
* a newly created table, with `grammar`'s keys and values.
--]]
function copy(grammar)
	local newt = {}

	for k, v in pairs(grammar) do
		newt[k] = v
	end

	return newt
end

--[[
[#section_Completing Completes] `dest` with `orig`.

**Parameters:**
* `dest`: the new grammar. Must be a table.
* `orig`: the original grammar. Must be a table.

**Returns:**
* `dest`, with new rules inherited from `orig`.
--]]
function complete (dest, orig)
	for rule, patt in pairs(orig) do
		if not dest[rule] then
			dest[rule] = patt
		end
	end

	return dest
end

--[[
[#section_Piping Pipes] the captures in `orig` to the ones in `dest`.

`dest` and `orig` should be tables, with each key storing a capture function. Each capture in `dest` will be altered to use the results for the matching one in `orig` as input, using function composition. Should `orig` possess keys not in `dest`, `dest` will copy them.

**Parameters:**
* `dest`: a capture table.
* `orig`: a capture table.

**Returns:**
* `dest`, suitably modified.
--]]
function pipe (dest, orig)
	for k, vorig in pairs(orig) do
		local vdest = dest[k]
		if vdest then
			dest[k] = function(...) return vdest(vorig(...)) end
		else
			dest[k] = vorig
		end
	end

	return dest
end

--[[
[#section_Completing Completes] `rules` with `grammar` and then [#Applying applies] `captures`.

`rules` can either be:
* a single pattern, which is taken to be the new initial rule,
* a possibly incomplete LPeg grammar, as per [#function_complete complete], or
* `nil`, which means no new rules are added.

`captures` can either be:
* a capture table, as per [#function_pipe pipe], or
* `nil`, which means no captures are applied.

**Parameters:**
* `grammar`: the old grammar. It stays unmodified.
* `rules`: optional, the new rules.
* `captures`: optional, the final capture table.

**Returns:**
* `rules`, suitably augmented by `grammar` and `captures`.
--]]
function apply (grammar, rules, captures)
  if rules == nil then
    rules = {}
  elseif type(rules) ~= 'table' then
    rules = { rules }
  end

  complete(rules, grammar)

  if type(grammar[1]) == 'string' then
    rules[1] = lpeg.V(grammar[1])
  end

	if captures ~= nil then
		assert(type(captures) == 'table', 'captures must be a table')

		for rule, cap in pairs(captures) do
			rules[rule] = rules[rule] / cap
		end
	end

	return rules
end
